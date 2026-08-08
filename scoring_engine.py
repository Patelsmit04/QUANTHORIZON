"""
BTST 5-PILLAR CONFIRMATION SCORING ENGINE (AUDITED & REFACTORED V2)
===================================================================
1. Futures OI + Price Relationship: Requires magnitude threshold (> 1.5x same-symbol 10-session
   avg OI % change). NOTE: real futures OI is not currently wired in — oi_data is a same-stock
   volume-based proxy (see nse_data_provider.py) unless the caller supplies genuine OI data.
   - Expiry Window (Configurable Expiry Calendar / Last Tuesday of Month + 2 Sessions): Halves Pillar 1 weight contribution to 0.5.
2. Same-Day Volume Persistence: trailing-candle volume (as of scan time) >= 1.5x an intraday
   session baseline (NOT a true cross-day 10-day average — no multi-day intraday history is
   fetched). Combined with T+1 Delivery % Validation (delivery % >= 1.15x 10d avg delivery):
   full weight when both agree or delivery data is unavailable, partial (0.5) weight when
   delivery contradicts the same-day volume signal.
3. Relative Strength vs Nifty 50 Index (|diff| >= 0.4%, direction must agree with the
   VWAP/RSI-derived bullish/bearish bias — outperformance for BTST, underperformance for STBT).
4. Volume Spike vs intraday session baseline (5-min Surge >= 1.8x; same baseline-scope caveat as
   Pillar 2 — not a genuine 10-day average).
5. Marubozu-Style Price Close: Normalized Intraday Range Position (0% = Low, 100% = High).
   - Bullish Marubozu Close: Range Position >= 98.0%
   - Bearish Marubozu Close: Range Position <= 2.0%
6. Institutional Flow (Bulk/Block Deals): Tiered by aggregated same-day net institutional value
   per symbol (see block_deal_provider.py) — WEAK (Rs25-50cr, weight 0.5), MODERATE (Rs50-150cr,
   weight 1.0), STRONG (Rs150cr+, weight 1.5). Direction-gated like Pillar 3 (only confirms when
   it agrees with the tentative VWAP/RSI bias); sell-side confirmation is dampened 0.7x relative
   to buy-side, since institutional selling is more often rebalancing/liquidity-driven than a
   conviction call. Governed by a shadow-mode flag (institutional_flow_shadow_mode) — while on,
   the pillar is fully computed and returned for transparency but excluded from
   confirmed_pillars_weight, so it cannot move the live verdict until reconciliation between the
   live NSE snapshot and the official EOD archive has been validated (see block_deal_provider.py).

Liquidity Tiering (enforced as the actual signal-validity gate, not just informational):
- TIER 1 (Nifty 50 / Top 30 Liquid F&O): Required Confirmation Weight >= 3.0
- TIER 2 (Rest of F&O Universe): Required Confirmation Weight >= 4.0
"""

import os
import json
import logging
import calendar
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

from fo_universe import is_valid_fo_stock

logger = logging.getLogger("BTSTScoringEngine")

IST = timezone(timedelta(hours=5, minutes=30))


def _get_ist_now() -> datetime:
    """IST-safe default clock so expiry-window detection doesn't depend on server local time."""
    return datetime.now(timezone.utc).astimezone(IST)

# Top 30 Liquid F&O Constituents (TIER_1)
TIER_1_STOCKS = {
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "M&M", "SBIN", 
    "AXISBANK", "LT", "MARUTI", "BAJFINANCE", "BAJAJFINSV", "TATASTEEL", "HINDALCO", 
    "BHARTIARTL", "KOTAKBANK", "HINDUNILVR", "SUNPHARMA", "ULTRACEMCO", "POWERGRID", 
    "NTPC", "TITAN", "ASIANPAINT", "ADANIPORTS", "ADANIENT", "GRASIM", "JSWSTEEL", 
    "CIPLA", "DRREDDY"
}

# Optional Custom Expiry Dates Override (Format: "YYYY-MM-DD")
EXPIRY_DATE_OVERSET: Dict[str, str] = {
    # Custom holiday adjustments if needed
}


def get_liquidity_tier(symbol: str) -> str:
    """Classify stock into TIER_1 (top 30 liquid F&O) or TIER_2 (rest of F&O). Non-F&O returns INVALID_NON_FO."""
    clean_sym = symbol.replace(".NS", "").upper()
    if not is_valid_fo_stock(clean_sym):
        return "INVALID_NON_FO"
    return "TIER_1" if clean_sym in TIER_1_STOCKS else "TIER_2"


def get_monthly_expiry_date(year: int, month: int, expiry_weekday: int = 1) -> date:
    """
    Calculate monthly expiry date for NSE F&O.
    NSE Stock Derivatives Monthly Expiry rule: Last Tuesday of the month (expiry_weekday = 1).
    (Tuesday = 1, Thursday = 3).
    """
    last_day = calendar.monthrange(year, month)[1]
    for day in range(last_day, 0, -1):
        d = date(year, month, day)
        if d.weekday() == expiry_weekday:
            return d
    return date(year, month, last_day)


def is_monthly_expiry_window(
    eval_date: Optional[datetime] = None,
    expiry_weekday: int = 1,
    post_expiry_sessions: int = 2
) -> bool:
    """
    Check if eval_date is monthly expiry day (last Tuesday of month for NSE stock F&O)
    or within N trading sessions post-expiry.
    """
    if eval_date is None:
        eval_date = _get_ist_now()

    year = eval_date.year
    month = eval_date.month
    month_key = f"{year}-{month:02d}"

    # Check custom overset calendar first
    if month_key in EXPIRY_DATE_OVERSET:
        expiry_dt = datetime.strptime(EXPIRY_DATE_OVERSET[month_key], "%Y-%m-%d").date()
    else:
        # Default: Last Tuesday of current month
        expiry_dt = get_monthly_expiry_date(year, month, expiry_weekday=expiry_weekday)

    current_date = eval_date.date()
    days_diff = (current_date - expiry_dt).days
    return 0 <= days_diff <= post_expiry_sessions


def evaluate_5_pillar_matrix(
    symbol: str,
    df_stock: pd.DataFrame,
    df_nifty: Optional[pd.DataFrame] = None,
    oi_data: Optional[Dict[str, Any]] = None,
    delivery_data: Optional[Dict[str, Any]] = None,
    oi_magnitude_mult: float = 1.5,
    eval_date: Optional[datetime] = None,
    fundamental_data: Optional[Dict[str, Any]] = None,
    pillar_weight_multipliers: Optional[Dict[str, float]] = None,
    required_weight_override: Optional[float] = None,
    institutional_flow_data: Optional[Dict[str, Any]] = None,
    institutional_flow_shadow_mode: bool = True
) -> Dict[str, Any]:
    """
    Evaluates stock against the Refactored 5-Pillar Matrix (now 6, with Institutional Flow —
    the name is kept for backward compatibility with existing call sites/journal columns).

    fundamental_data (optional): output of fundamental_provider.get_fundamental_data(). This is
    a QUALITY GATE, not a technical pillar — it doesn't add pillar weight (fundamentals move on
    a different timescale than an intraday BTST signal), it caps conviction when the underlying
    business looks structurally shaky (WEAK/CAUTION verdicts), regardless of how clean the
    technical setup looks. FAIL LOUD: if unavailable, no cap is applied — never fabricated.

    pillar_weight_multipliers (optional): output of
    walk_forward_validator.get_active_pillar_weights() — per-pillar multipliers empirically
    tuned from evaluated outcome history (capped +/-15%/day, gated on >=30 samples; see that
    module), OR strategy_manager.compute_effective_pillar_multipliers() when a strategy has
    disabled specific pillars (multiplier 0.0). Defaults to None, meaning every pillar keeps
    its original 1.0 weight.

    required_weight_override (optional): replaces the tier-based required_pillars threshold
    (3 for TIER_1, 4 for TIER_2) with a caller-supplied value — used by strategy_manager to
    let a strategy define its own confirmation bar. None (default) keeps the tier-based rule.

    institutional_flow_data (optional): output of
    block_deal_provider.get_institutional_flow_data() — same-day aggregated net bulk/block deal
    value for this symbol. None (default, FAIL LOUD) excludes Pillar 6 from scoring entirely,
    same convention as oi_data/delivery_data above.

    institutional_flow_shadow_mode (default True): while True, Pillar 6 is still fully computed
    and returned in the response (institutional_flow block) but its weight is excluded from
    confirmed_pillars/pillar_weights, so it cannot affect total_confirmed_weight or the signal
    derived from it — see block_deal_provider.py's module docstring for why (unreconciled live
    NSE data). Flip to False only after that reconciliation has run clean for a couple of weeks.
    """
    weight_mult = pillar_weight_multipliers or {}

    def _mult(pillar_name: str) -> float:
        return weight_mult.get(pillar_name, 1.0)
    clean_sym = symbol.replace(".NS", "").upper()
    
    # ENFORCE WHITELIST CHECK: Reject any stock not in active NSE F&O universe
    if not is_valid_fo_stock(clean_sym):
        return {
            "symbol": clean_sym,
            "raw_ticker": symbol,
            "liquidity_tier": "INVALID_NON_FO",
            "required_pillars": 999,
            "confirmed_pillars_count": 0,
            "confirmed_pillars_weight": 0.0,
            "confirmed_pillars": [],
            "signal": "REJECTED_NON_FO",
            "reason": "Stock is NOT in active NSE F&O whitelist — no option chain available."
        }

    liquidity_tier = get_liquidity_tier(clean_sym)
    required_pillars = required_weight_override if required_weight_override is not None else (3 if liquidity_tier == "TIER_1" else 4)

    if df_stock is None or df_stock.empty:
        return {
            "symbol": clean_sym,
            "liquidity_tier": liquidity_tier,
            "required_pillars": required_pillars,
            "confirmed_pillars_count": 0,
            "confirmed_pillars_weight": 0.0,
            "signal": "NEUTRAL",
            "reason": "Insufficient intraday data"
        }

    # Clean NaNs and make explicit copy to prevent SettingWithCopyWarning
    df_stock = df_stock.dropna(subset=['Close', 'Open', 'High', 'Low', 'Volume']).copy()
    if len(df_stock) < 15:
        return {
            "symbol": clean_sym,
            "liquidity_tier": liquidity_tier,
            "required_pillars": required_pillars,
            "confirmed_pillars_count": 0,
            "confirmed_pillars_weight": 0.0,
            "signal": "NEUTRAL",
            "option_type": "NONE",
            "conviction_level": "WATCHLIST",
            "priority_level": "P3_LOW",
            "confidence_score": 40,
            "reason": "Insufficient intraday data"
        }

    latest = df_stock.iloc[-1]
    prev_close = float(df_stock.iloc[0]['Open'])
    daily_high = float(df_stock['High'].max())
    daily_low = float(df_stock['Low'].min())
    ltp = float(latest['Close'])
    
    # Intraday Indicators
    df_stock['Cum_Vol'] = df_stock['Volume'].cumsum()
    df_stock['Cum_Vol_Price'] = (df_stock['Close'] * df_stock['Volume']).cumsum()
    vwap = float(np.where(df_stock['Cum_Vol'] > 0, df_stock['Cum_Vol_Price'] / df_stock['Cum_Vol'], df_stock['Close'])[-1])
    
    # Baseline EXCLUDES the trailing 6-candle window used by the spike/persistence checks below —
    # otherwise the "spike" is counted inside its own baseline average, which mechanically damps
    # the computed ratio. This is an intraday same-session baseline (NOT a true cross-day 10-day
    # average — no multi-day intraday volume history is fetched here).
    _recent_window_size = min(6, len(df_stock))
    _baseline_candles = df_stock.iloc[:-_recent_window_size] if len(df_stock) > _recent_window_size else df_stock
    vol_sma_20 = float(_baseline_candles['Volume'].tail(20).mean()) if not _baseline_candles.empty else float(df_stock['Volume'].mean())
    vol_sma_20 = max(1.0, vol_sma_20)

    # Calculate RSI (14)
    delta = df_stock['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.fillna(50.0).iloc[-1])

    # Trailing candles as of whenever this scan runs (near close during the 3:30 PM lock window,
    # but this same function also runs on every intraday 5-min/1-min scan tick).
    recent_candles = df_stock.iloc[-min(4, len(df_stock)):]
    max_recent_vol = float(recent_candles['Volume'].max())
    vol_spike_ratio = round(max_recent_vol / vol_sma_20, 2)

    stock_pct_change = round(((ltp - prev_close) / prev_close) * 100, 2)
    
    # =========================================================================
    # FIX FOR ISSUE #3: MARUBOZU RANGE POSITION PERCENTAGE (0% to 100%)
    # =========================================================================
    day_range = daily_high - daily_low
    if day_range > 0:
        range_position_pct = round(max(0.0, min(100.0, ((ltp - daily_low) / day_range) * 100.0)), 2)
    else:
        range_position_pct = 50.0

    expiry_discounted = is_monthly_expiry_window(eval_date, expiry_weekday=1)

    # Tentative directional bias from VWAP + RSI, computed up front so direction-sensitive
    # pillars (3) only get credit when they agree with it, instead of confirming on magnitude alone.
    bullish_bias = ltp > vwap and rsi >= 55
    bearish_bias = ltp < vwap and rsi <= 45

    confirmed_pillars = []
    pillar_weights = {}

    # =========================================================================
    # PILLAR 1: Futures OI + Price Relationship (Magnitude Threshold & Expiry Weight Halving)
    # FAIL LOUD: If oi_data is None, mark as DATA_UNAVAILABLE — do NOT use fallback constant
    # =========================================================================
    p1_confirmed = False
    p1_weight = 0.0
    p1_data_status = "DATA_UNAVAILABLE"
    oi_pct_change = 0.0
    avg_10d_oi_pct = 0.0
    oi_threshold = 0.0
    is_oi_above_threshold = False

    if oi_data is not None:
        p1_data_status = oi_data.get("source", "PROVIDED")
        oi_pct_change = float(oi_data.get("oi_pct_change", 0.0))
        avg_10d_oi_pct = float(oi_data.get("avg_10d_oi_pct", 0.0))
        oi_threshold = avg_10d_oi_pct * oi_magnitude_mult

        # STRICT MAGNITUDE REQUIREMENT: Must exceed multiplier threshold
        is_oi_above_threshold = abs(oi_pct_change) >= oi_threshold if oi_threshold > 0 else False

        if ltp > vwap and oi_pct_change > 0 and is_oi_above_threshold:
            p1_confirmed = True
            p1_weight = (0.5 if expiry_discounted else 1.0) * _mult("Pillar 1: Futures OI")
            confirmed_pillars.append(f"Pillar 1: OI Long Buildup (Weight: {p1_weight:.2f})")
        elif ltp < vwap and oi_pct_change < 0 and is_oi_above_threshold:
            p1_confirmed = True
            p1_weight = (0.5 if expiry_discounted else 1.0) * _mult("Pillar 1: Futures OI")
            confirmed_pillars.append(f"Pillar 1: OI Short Buildup (Weight: {p1_weight:.2f})")
    else:
        # FAIL LOUD: No OI data — pillar excluded from scoring entirely
        logger.warning(f"[{clean_sym}] Pillar 1 OI: DATA_UNAVAILABLE — excluded from pillar count")

    pillar_weights["Pillar 1: Futures OI"] = p1_weight

    # =========================================================================
    # PILLAR 2: Same-Day Volume Persistence (trailing window as of scan time)
    #            + T+1 Delivery % Validation — combined per the two-part design above.
    # =========================================================================
    # Pre-9:15 AM Delivery % Validation (T+1) — computed first so Pillar 2 can combine it.
    # FAIL LOUD: If delivery_data is None, mark as DATA_UNAVAILABLE
    delivery_t1_confirmed = None
    delivery_pct = None
    avg_10d_delivery = None
    delivery_data_status = "DATA_UNAVAILABLE"
    if delivery_data is not None:
        delivery_data_status = delivery_data.get("source", "PROVIDED")
        delivery_pct = float(delivery_data.get("delivery_pct", 0.0))
        avg_10d_delivery = float(delivery_data.get("avg_10d_delivery_pct", 0.0))
        if avg_10d_delivery > 0:
            delivery_t1_confirmed = delivery_pct >= (1.15 * avg_10d_delivery)
        else:
            delivery_t1_confirmed = None
    else:
        logger.warning(f"[{clean_sym}] Delivery T+1: DATA_UNAVAILABLE — excluded from validation")

    late_candles = df_stock.iloc[-min(6, len(df_stock)):]
    late_vol_avg = float(late_candles['Volume'].mean())
    late_vol_ratio = round(late_vol_avg / vol_sma_20, 2)
    same_day_vol_confirmed = late_vol_ratio >= 1.5

    if same_day_vol_confirmed and delivery_t1_confirmed is True:
        # Both legs agree: full weight, strongest form of Pillar 2.
        p2_confirmed = True
        p2_weight = 1.0 * _mult("Pillar 2: Vol Persistence")
        confirmed_pillars.append(f"Pillar 2: Vol Persistence ({late_vol_ratio}x) + T+1 Delivery Confirmed")
    elif same_day_vol_confirmed and delivery_t1_confirmed is None:
        # Delivery data unavailable — fail loud on that leg only, don't fabricate a confirmation,
        # but don't discard the same-day volume evidence that IS known.
        p2_confirmed = True
        p2_weight = 1.0 * _mult("Pillar 2: Vol Persistence")
        confirmed_pillars.append(f"Pillar 2: Vol Persistence ({late_vol_ratio}x) [Delivery data unavailable]")
    elif same_day_vol_confirmed and delivery_t1_confirmed is False:
        # Same-day volume is up, but T+1 delivery trend contradicts it — partial credit only.
        p2_confirmed = True
        p2_weight = 0.5 * _mult("Pillar 2: Vol Persistence")
        confirmed_pillars.append(f"Pillar 2: Vol Persistence Only ({late_vol_ratio}x) [Delivery NOT confirmed]")
    else:
        p2_confirmed = False
        p2_weight = 0.0

    pillar_weights["Pillar 2: Vol Persistence"] = p2_weight

    # =========================================================================
    # PILLAR 3: Relative Strength vs Nifty 50 Index
    # =========================================================================
    p3_confirmed = False
    p3_weight = 0.0
    nifty_pct_change = 0.0
    if df_nifty is not None and not df_nifty.empty:
        n_prev_close = float(df_nifty.iloc[0]['Open'])
        n_ltp = float(df_nifty.iloc[-1]['Close'])
        nifty_pct_change = round(((n_ltp - n_prev_close) / n_prev_close) * 100, 2)

    rs_diff = round(stock_pct_change - nifty_pct_change, 2)
    # Require the RS divergence to point the SAME way as the tentative bias, not just be large —
    # a stock underperforming Nifty by >0.4% must not count as "confirmation" toward a bullish call.
    if bullish_bias and rs_diff >= 0.4:
        p3_confirmed = True
        p3_weight = 1.0 * _mult("Pillar 3: Relative Strength")
        confirmed_pillars.append(f"Pillar 3: RS vs Nifty (Outperforming +{rs_diff}%)")
    elif bearish_bias and rs_diff <= -0.4:
        p3_confirmed = True
        p3_weight = 1.0 * _mult("Pillar 3: Relative Strength")
        confirmed_pillars.append(f"Pillar 3: RS vs Nifty (Underperforming {rs_diff}%)")

    pillar_weights["Pillar 3: Relative Strength"] = p3_weight

    # =========================================================================
    # PILLAR 4: Volume Spike vs 10-Day Average (5-min Surge)
    # =========================================================================
    p4_confirmed = vol_spike_ratio >= 1.8
    p4_weight = (1.0 * _mult("Pillar 4: Volume Spike")) if p4_confirmed else 0.0
    if p4_confirmed:
        confirmed_pillars.append(f"Pillar 4: Vol Spike ({vol_spike_ratio}x)")

    pillar_weights["Pillar 4: Volume Spike"] = p4_weight

    # =========================================================================
    # PILLAR 5: Final 15-20 Min Price Close (Normalized Marubozu Range Position)
    # =========================================================================
    # Range Position >= 98% (Bullish Close near High) or <= 2% (Bearish Close near Low)
    p5_confirmed = (range_position_pct >= 98.0) or (range_position_pct <= 2.0)
    p5_weight = (1.0 * _mult("Pillar 5: Marubozu Close")) if p5_confirmed else 0.0
    if p5_confirmed:
        confirmed_pillars.append(f"Pillar 5: Marubozu Close (Range Pos: {range_position_pct}%)")

    pillar_weights["Pillar 5: Marubozu Close"] = p5_weight

    # =========================================================================
    # PILLAR 6: Institutional Flow (Bulk/Block Deals) — see block_deal_provider.py.
    # FAIL LOUD: if institutional_flow_data is None, DATA_UNAVAILABLE — excluded entirely.
    # =========================================================================
    SELL_SIDE_DAMPENING = 0.7  # institutional selling is weaker conviction signal than buying
    TIER_WEIGHTS = {"WEAK": 0.5, "MODERATE": 1.0, "STRONG": 1.5}

    p6_data_status = "DATA_UNAVAILABLE"
    p6_tier = None
    p6_dominant_side = None
    p6_net_value_cr = 0.0
    p6_would_confirm = False
    p6_would_weight = 0.0

    if institutional_flow_data is not None:
        p6_data_status = institutional_flow_data.get("source", "PROVIDED")
        p6_tier = institutional_flow_data.get("tier", "BELOW_THRESHOLD")
        p6_dominant_side = institutional_flow_data.get("dominant_side", "NONE")
        p6_net_value_cr = float(institutional_flow_data.get("net_value_cr", 0.0))
        tier_weight = TIER_WEIGHTS.get(p6_tier, 0.0)

        if tier_weight > 0 and bullish_bias and p6_dominant_side == "BUY":
            p6_would_confirm = True
            p6_would_weight = round(tier_weight * _mult("Pillar 6: Institutional Flow"), 4)
        elif tier_weight > 0 and bearish_bias and p6_dominant_side == "SELL":
            p6_would_confirm = True
            p6_would_weight = round(tier_weight * SELL_SIDE_DAMPENING * _mult("Pillar 6: Institutional Flow"), 4)
    else:
        logger.warning(f"[{clean_sym}] Pillar 6 Institutional Flow: DATA_UNAVAILABLE — excluded from pillar count")

    p6_confirmed = p6_would_confirm and not institutional_flow_shadow_mode
    p6_weight = p6_would_weight if p6_confirmed else 0.0
    if p6_confirmed:
        confirmed_pillars.append(f"Pillar 6: Institutional Flow ({p6_tier}, {p6_dominant_side} Rs{abs(p6_net_value_cr):.1f}cr)")

    pillar_weights["Pillar 6: Institutional Flow"] = p6_weight

    # Total confirmed count & weighted score
    total_confirmed_count = len(confirmed_pillars)
    total_confirmed_weight = sum(pillar_weights.values())

    # Signal & Threshold Evaluation
    signal = "NEUTRAL"
    option_type = "NONE"
    conviction_level = "WATCHLIST"
    
    # Liquidity-tiered threshold: TIER_1 needs >= 3.0, TIER_2 needs >= 4.0 (required_pillars).
    is_valid_signal = total_confirmed_weight >= required_pillars

    if is_valid_signal:
        # "One full pillar weight above the tier's own minimum" = high conviction, for both tiers.
        high_conviction_bar = required_pillars + 1.0
        if bullish_bias:
            signal = "BTST (BUY)"
            option_type = "CALL (CE)"
            conviction_level = "HIGH_CONVICTION" if total_confirmed_weight >= high_conviction_bar else "MODERATE"
        elif bearish_bias:
            signal = "STBT (SELL)"
            option_type = "PUT (PE)"
            conviction_level = "HIGH_CONVICTION" if total_confirmed_weight >= high_conviction_bar else "MODERATE"

    # Confidence Score Calculation — normalized by each tier's own required_pillars so a TIER_1
    # stock at its minimum (3.0) and a TIER_2 stock at its minimum (4.0) start from the same base,
    # and the volume-spike term is capped so one outsized spike alone can't max out the score.
    weight_ratio = total_confirmed_weight / required_pillars
    capped_vol_spike = min(vol_spike_ratio, 3.0)
    base_score = int(50 + (weight_ratio * 27) + (capped_vol_spike * 2.5))
    if p5_confirmed:
        base_score += 5
    confidence_score = min(99, max(40, base_score))

    # Priority Level Determination (Score-Based & Signal-Driven)
    if signal in ["BTST (BUY)", "STBT (SELL)"]:
        if confidence_score >= 90:
            priority_level = "P1_HIGH"
        elif confidence_score >= 75:
            priority_level = "P2_MEDIUM"
        else:
            priority_level = "P3_LOW"
    else:
        priority_level = "P3_LOW"

    # =========================================================================
    # FUNDAMENTAL QUALITY GATE: caps conviction when the underlying business looks
    # structurally shaky, regardless of how clean the technical setup is. Never upgrades a
    # signal — only ever holds it back. FAIL LOUD: no fundamental_data means no cap.
    # =========================================================================
    fundamental_gate_applied = None
    fundamental_verdict = "UNAVAILABLE"
    if fundamental_data is not None:
        quality = fundamental_data.get("quality", {})
        fundamental_verdict = quality.get("verdict", "UNKNOWN")
        if fundamental_verdict == "WEAK" and priority_level != "P3_LOW":
            fundamental_gate_applied = f"Capped {priority_level} -> P3_LOW (fundamental verdict: WEAK)"
            priority_level = "P3_LOW"
            conviction_level = "MODERATE" if conviction_level == "HIGH_CONVICTION" else conviction_level
        elif fundamental_verdict == "CAUTION" and priority_level == "P1_HIGH":
            fundamental_gate_applied = "Capped P1_HIGH -> P2_MEDIUM (fundamental verdict: CAUTION)"
            priority_level = "P2_MEDIUM"
            conviction_level = "MODERATE"

    # Estimated Gap % Calculation
    est_gap = round(0.8 + (vol_spike_ratio * 0.5) + (abs(rsi - 50) * 0.04), 1)
    predicted_gap_pct = est_gap if (ltp >= vwap) else -est_gap

    reason_str = f"Confirmed {total_confirmed_weight}/{required_pillars} Pillar Weight [{liquidity_tier}]"
    if expiry_discounted:
        reason_str += " (Expiry OI Halving Discount Applied)"

    return {
        "symbol": clean_sym,
        "raw_ticker": symbol,
        "liquidity_tier": liquidity_tier,
        "required_pillars": required_pillars,
        "confirmed_pillars_count": total_confirmed_count,
        "confirmed_pillars_weight": round(total_confirmed_weight, 1),
        "confirmed_pillars": confirmed_pillars,
        "pillar_weights": pillar_weights,
        "oi_magnitude": {
            "actual_oi_pct": oi_pct_change,
            "avg_10d_oi_pct": avg_10d_oi_pct,
            "multiplier_used": oi_magnitude_mult,
            "threshold": oi_threshold,
            "is_above_threshold": is_oi_above_threshold,
            "data_status": p1_data_status
        },
        "expiry_discount_applied": expiry_discounted,
        "delivery_t1_validation": {
            "delivery_pct": delivery_pct,
            "avg_10d_delivery_pct": avg_10d_delivery,
            "delivery_t1_confirmed": delivery_t1_confirmed,
            "data_status": delivery_data_status
        },
        "institutional_flow": {
            "tier": p6_tier,
            "dominant_side": p6_dominant_side,
            "net_value_cr": p6_net_value_cr,
            "buy_value_cr": institutional_flow_data.get("buy_value_cr") if institutional_flow_data else None,
            "sell_value_cr": institutional_flow_data.get("sell_value_cr") if institutional_flow_data else None,
            "deal_types": institutional_flow_data.get("deal_types") if institutional_flow_data else None,
            "as_of": institutional_flow_data.get("as_of") if institutional_flow_data else None,
            "shadow_mode": institutional_flow_shadow_mode,
            "would_confirm": p6_would_confirm,
            "would_weight": round(p6_would_weight, 2),
            "data_status": p6_data_status
        },
        "fundamental_quality": {
            "verdict": fundamental_verdict,
            "gate_applied": fundamental_gate_applied,
            "sector": fundamental_data.get("sector") if fundamental_data else None,
            "trailing_pe": fundamental_data.get("trailingPE") if fundamental_data else None,
            "return_on_equity": fundamental_data.get("returnOnEquity") if fundamental_data else None,
            "debt_to_equity": fundamental_data.get("debtToEquity") if fundamental_data else None,
            "earnings_growth": fundamental_data.get("earningsGrowth") if fundamental_data else None,
            "red_flags": fundamental_data.get("quality", {}).get("red_flags", []) if fundamental_data else [],
            "yellow_flags": fundamental_data.get("quality", {}).get("yellow_flags", []) if fundamental_data else [],
            "data_status": "STALE_CACHE" if (fundamental_data and fundamental_data.get("stale")) else ("AVAILABLE" if fundamental_data else "DATA_UNAVAILABLE")
        },
        "signal": signal,
        "option_type": option_type,
        "conviction_level": conviction_level,
        "priority_level": priority_level,
        "confidence_score": confidence_score,
        "predicted_gap_pct": predicted_gap_pct,
        "ltp": round(ltp, 2),
        "day_high": round(daily_high, 2),
        "day_low": round(daily_low, 2),
        "range_position_pct": range_position_pct,
        "vwap": round(vwap, 2),
        "volume_spike": vol_spike_ratio,
        "rsi": round(rsi, 1),
        "pct_change": stock_pct_change,
        "rank_reason": reason_str,
        "score": confidence_score
    }
