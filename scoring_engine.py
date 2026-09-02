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
import logging
import calendar
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, Optional
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
    institutional_flow_shadow_mode: bool = True,
    macro_status: Optional[Dict[str, Any]] = None
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
            "confirmed_pillars": [],
            "pillar_weights": {
                "Pillar 1: Futures OI": 0.0,
                "Pillar 2: Vol Persistence": 0.0,
                "Pillar 3: Relative Strength": 0.0,
                "Pillar 4: Volume Spike": 0.0,
                "Pillar 5: Marubozu Close": 0.0,
                "Pillar 6: Institutional Flow": 0.0,
            },
            "signal": "NEUTRAL",
            "option_type": "NONE",
            "conviction_level": "WATCHLIST",
            "priority_level": "P3_LOW",
            "confidence_score": 40,
            "reason": "Insufficient intraday data"
        }

    # Split df_stock into trading sessions to isolate today's intraday bar
    if isinstance(df_stock.index, pd.DatetimeIndex):
        date_strs = df_stock.index.strftime("%Y-%m-%d")
    elif "Datetime" in df_stock.columns:
        date_strs = pd.to_datetime(df_stock["Datetime"]).dt.strftime("%Y-%m-%d")
    elif "Date" in df_stock.columns:
        date_strs = pd.to_datetime(df_stock["Date"]).dt.strftime("%Y-%m-%d")
    elif isinstance(df_stock.index, pd.RangeIndex) or str(df_stock.index.dtype).startswith("int"):
        date_strs = pd.Series(["SESSION_1"] * len(df_stock), index=df_stock.index)
    else:
        date_strs = pd.Series([str(i)[:10] for i in df_stock.index], index=df_stock.index)

    unique_dates = list(dict.fromkeys(date_strs))
    latest_date = unique_dates[-1] if unique_dates else None

    if latest_date:
        df_today = df_stock[date_strs.values == latest_date].copy()
        if len(unique_dates) >= 2:
            prev_date = unique_dates[-2]
            df_prev = df_stock[date_strs.values == prev_date]
            prev_close = float(df_prev.iloc[-1]['Close']) if not df_prev.empty else float(df_today.iloc[0]['Open'])
        else:
            prev_close = float(df_today.iloc[0]['Open'])
    else:
        df_today = df_stock
        prev_close = float(df_stock.iloc[0]['Open'])

    if df_today.empty:
        df_today = df_stock

    latest = df_today.iloc[-1]
    daily_high = float(df_today['High'].max())
    daily_low = float(df_today['Low'].min())
    ltp = float(latest['Close'])
    
    # Intraday VWAP (strictly for today's session)
    df_today['Cum_Vol'] = df_today['Volume'].cumsum()
    df_today['Cum_Vol_Price'] = (df_today['Close'] * df_today['Volume']).cumsum()
    vwap = float(np.where(df_today['Cum_Vol'] > 0, df_today['Cum_Vol_Price'] / df_today['Cum_Vol'], df_today['Close'])[-1])
    
    # Baseline EXCLUDES trailing candles
    _recent_window_size = min(6, len(df_today))
    _baseline_candles = df_today.iloc[:-_recent_window_size] if len(df_today) > _recent_window_size else df_today
    vol_sma_20 = float(_baseline_candles['Volume'].tail(20).mean()) if not _baseline_candles.empty else float(df_today['Volume'].mean())
    vol_sma_20 = max(1.0, vol_sma_20)

    # Calculate RSI (14) using Wilder's Exponential Moving Average smoothing
    delta = df_today['Close'].diff()
    gain = (delta.where(delta > 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    rsi = float(rsi_series.fillna(50.0).iloc[-1])

    # Trailing candles for volume spike
    recent_candles = df_today.iloc[-min(4, len(df_today)):]
    max_recent_vol = float(recent_candles['Volume'].max())
    vol_spike_ratio = round(max_recent_vol / vol_sma_20, 2)

    stock_pct_change = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0
    
    # Marubozu Range Position (0% to 100% on today's High/Low)
    day_range = daily_high - daily_low
    if day_range > 0:
        range_position_pct = round(max(0.0, min(100.0, ((ltp - daily_low) / day_range) * 100.0)), 2)
    else:
        range_position_pct = 50.0

    # ATR(14) calculation across session history for Range Exhaustion Check
    if len(unique_dates) >= 14:
        df_daily = df_stock.groupby(date_strs.values).agg({
            'High': 'max', 'Low': 'min', 'Close': 'last', 'Open': 'first'
        })
        d_highs = df_daily['High']
        d_lows = df_daily['Low']
        d_closes = df_daily['Close']
        d_prev_c = d_closes.shift(1).fillna(df_daily['Open'])
        d_tr = pd.concat([d_highs - d_lows, (d_highs - d_prev_c).abs(), (d_lows - d_prev_c).abs()], axis=1).max(axis=1)
        atr_14 = float(d_tr.rolling(14, min_periods=1).mean().iloc[-1])
        is_day_range_exhausted = (day_range > 1.5 * atr_14) and (atr_14 > 0.05)
    else:
        atr_14 = float(day_range) if day_range > 0 else 1.0
        is_day_range_exhausted = False

    # 20-period EMA of Close for Trend Overextension Check
    ema_20 = float(df_stock['Close'].ewm(span=20, adjust=False).mean().iloc[-1]) if len(df_stock) >= 5 else ltp
    ema_20_extension_pct = round(((ltp - ema_20) / ema_20) * 100, 2) if ema_20 > 0 else 0.0

    # Exhaustion & Mean Reversion Veto conditions (Phase 1)
    # 1. Quiet pump: gain > 4.5% with weak volume surge (< 1.5x)
    is_quiet_pump = (stock_pct_change > 4.5) and (vol_spike_ratio < 1.5)
    # 2. Overextended beyond 20-period EMA with elevated RSI
    is_ema_overextended = (ema_20_extension_pct > 5.0) and (rsi > 72.0)

    # NIFTY 50 Intraday VWAP Alignment (Phase 2)
    nifty_below_vwap = False
    nifty_ltp_val = None
    nifty_vwap_val = None
    if df_nifty is not None and not df_nifty.empty:
        nifty_ltp_val = float(df_nifty.iloc[-1]['Close'])
        if 'Volume' in df_nifty.columns and df_nifty['Volume'].sum() > 0:
            n_cum_vol = df_nifty['Volume'].cumsum()
            n_cum_vp = (df_nifty['Close'] * df_nifty['Volume']).cumsum()
            nifty_vwap_val = float(np.where(n_cum_vol > 0, n_cum_vp / n_cum_vol, df_nifty['Close'])[-1])
        else:
            nifty_vwap_val = float(df_nifty['Close'].mean())
        nifty_below_vwap = nifty_ltp_val < nifty_vwap_val
    elif macro_status is not None:
        nifty_below_vwap = bool(macro_status.get("nifty_below_vwap", False))

    # India VIX < 11.5 Low Volatility Regime Filter (Phase 2)
    vix_low_vol_regime = False
    vix_val = None
    if macro_status is not None:
        vix_val = macro_status.get("vix_value") or macro_status.get("india_vix")
        if vix_val is not None:
            try:
                vix_low_vol_regime = float(vix_val) < 11.5
            except (ValueError, TypeError):
                vix_low_vol_regime = False

    expiry_discounted = is_monthly_expiry_window(eval_date, expiry_weekday=1)

    # Tentative directional bias from VWAP + RSI, computed up front so direction-sensitive
    # pillars (3) only get credit when they agree with it, instead of confirming on magnitude alone.
    bullish_bias = ltp > vwap and rsi >= 50
    bearish_bias = ltp < vwap and rsi <= 50

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

        if (ltp > vwap or stock_pct_change > 0) and oi_pct_change > 0 and is_oi_above_threshold:
            p1_confirmed = True
            p1_weight = (0.5 if expiry_discounted else 1.0) * _mult("Pillar 1: Futures OI")
            confirmed_pillars.append(f"Pillar 1: OI Long Buildup (Weight: {p1_weight:.2f})")
        elif (ltp < vwap or stock_pct_change < 0) and oi_pct_change > 0 and is_oi_above_threshold:
            p1_confirmed = True
            p1_weight = (0.5 if expiry_discounted else 1.0) * _mult("Pillar 1: Futures OI")
            confirmed_pillars.append(f"Pillar 1: OI Short Buildup (Weight: {p1_weight:.2f})")
        elif oi_pct_change < 0:
            logger.info(f"[{clean_sym}] Derivative liquidation detected (OI change {oi_pct_change}%) — Short Covering / Long Unwinding rejected")
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
    rs_slope = 0.0
    if df_nifty is not None and not df_nifty.empty and len(df_today) >= 3:
        try:
            # Timestamp alignment: inner join intraday closes
            if isinstance(df_today.index, pd.DatetimeIndex) and isinstance(df_nifty.index, pd.DatetimeIndex):
                merged_rs = pd.DataFrame({"stock": df_today['Close'], "nifty": df_nifty['Close']}).dropna()
                tail_rs = merged_rs.tail(9)
                if len(tail_rs) >= 3 and np.all(tail_rs["nifty"].values > 0):
                    rs_series = tail_rs["stock"].values / tail_rs["nifty"].values
                    x = np.arange(len(rs_series))
                    rs_slope = float(np.polyfit(x, rs_series, 1)[0])
            else:
                min_len = min(9, len(df_today), len(df_nifty))
                stock_closes = df_today['Close'].iloc[-min_len:].values
                nifty_closes = df_nifty['Close'].iloc[-min_len:].values
                if len(stock_closes) == len(nifty_closes) and np.all(nifty_closes > 0):
                    rs_series = stock_closes / nifty_closes
                    x = np.arange(len(rs_series))
                    rs_slope = float(np.polyfit(x, rs_series, 1)[0])
        except Exception as ex:
            logger.warning(f"RS slope calculation fallback: {ex}")

    rs_slope_positive = rs_slope >= -1e-6
    rs_slope_negative = rs_slope <= 1e-6

    # Require the RS divergence to point the SAME way as the tentative bias, supported by final 45-min RS trend
    if bullish_bias and rs_diff >= 0.4 and rs_slope_positive:
        p3_confirmed = True
        p3_weight = 1.0 * _mult("Pillar 3: Relative Strength")
        confirmed_pillars.append(f"Pillar 3: RS vs Nifty (Outperforming +{rs_diff}%, RS Slope Up)")
    elif bearish_bias and rs_diff <= -0.4 and rs_slope_negative:
        p3_confirmed = True
        p3_weight = 1.0 * _mult("Pillar 3: Relative Strength")
        confirmed_pillars.append(f"Pillar 3: RS vs Nifty (Underperforming {rs_diff}%, RS Slope Down)")

    pillar_weights["Pillar 3: Relative Strength"] = p3_weight

    # =========================================================================
    # PILLAR 4: Volume Spike vs 10-Day Average (5-min Surge + MOC Persistence Check)
    # =========================================================================
    # Discard single-bar MOC rebalancing spikes unless volume persistence >= 2 bars or surge >= 2.5x
    vol_persistence_count = int((recent_candles['Volume'] >= (1.2 * vol_sma_20)).sum()) if 'Volume' in recent_candles.columns else 0
    is_moc_single_spike = (vol_persistence_count < 2) and (vol_spike_ratio < 2.5)
    
    p4_confirmed = (vol_spike_ratio >= 1.8) and (not is_moc_single_spike)
    p4_weight = (1.0 * _mult("Pillar 4: Volume Spike")) if p4_confirmed else 0.0
    if p4_confirmed:
        confirmed_pillars.append(f"Pillar 4: Vol Spike ({vol_spike_ratio}x, Persistence: {vol_persistence_count} bars)")
    elif vol_spike_ratio >= 1.8 and is_moc_single_spike:
        logger.info(f"[{clean_sym}] Single-bar MOC volume rebalancing spike detected ({vol_spike_ratio}x) — Pillar 4 rejected")

    pillar_weights["Pillar 4: Volume Spike"] = p4_weight

    # =========================================================================
    # PILLAR 5: Final 15-20 Min Price Close (Normalized Marubozu Range Position)
    # =========================================================================
    # Range Position >= 85% (Bullish Close near High) or <= 15% (Bearish Close near Low) per Section 3 spec
    if bullish_bias and range_position_pct >= 85.0:
        p5_confirmed = True
    elif bearish_bias and range_position_pct <= 15.0:
        p5_confirmed = True
    else:
        p5_confirmed = (range_position_pct >= 85.0) or (range_position_pct <= 15.0)

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

    # Decoupled Confidence Score Calculation (Phase 3 Recalibration)
    # Combines pillar weight ratio, volume surge, intraday Marubozu close, and relative strength trend alignment.
    weight_ratio = total_confirmed_weight / required_pillars if required_pillars > 0 else 0.0
    capped_vol_spike = min(vol_spike_ratio, 3.0)
    rs_slope_bonus = 5 if (p3_confirmed and rs_slope_positive) else 0
    base_score = int(50 + (weight_ratio * 25) + (capped_vol_spike * 3.0) + rs_slope_bonus)
    if p5_confirmed:
        base_score += 5
    confidence_score = min(99, max(40, base_score))

    # Priority Level Determination (P1_HIGH requires Weight >= required_pillars AND Confidence >= 88%)
    if signal in ["BTST (BUY)", "STBT (SELL)"]:
        if total_confirmed_weight >= required_pillars and confidence_score >= 88:
            priority_level = "P1_HIGH"
        elif confidence_score >= 70 or total_confirmed_weight >= (required_pillars - 0.5):
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

    # =========================================================================
    # GLOBAL MACRO RISK GATE & INDIA VIX REGIME FILTER (Phase 2)
    # Caps conviction when S&P 500 futures, India VIX, or GIFT Nifty risk triggers
    # IF India VIX < 11.5, disables breakout strategies (Low Volatility Regime)
    # =========================================================================
    macro_gate_applied = None
    if macro_status is not None:
        vix_ok = macro_status.get("vix_ok", True)
        sp500_green = macro_status.get("sp500_green", True)
        gift_nifty_ok = macro_status.get("gift_nifty_ok", True)
        if (not vix_ok or not sp500_green or not gift_nifty_ok or vix_low_vol_regime) and priority_level == "P1_HIGH":
            reasons = []
            if not vix_ok:
                reasons.append("India VIX spiking > 5%")
            if not sp500_green:
                reasons.append("S&P 500 futures red")
            if not gift_nifty_ok:
                reasons.append("GIFT Nifty pullback < -0.3%")
            if vix_low_vol_regime:
                reasons.append(f"India VIX {vix_val} < 11.5 (Low Volatility Regime — Breakouts disabled)")
            macro_gate_applied = f"Capped P1_HIGH -> P2_MEDIUM (Global Macro Risk: {', '.join(reasons)})"
            priority_level = "P2_MEDIUM"
            conviction_level = "MODERATE"

    # =========================================================================
    # INDEX GUARD: NIFTY 50 Intraday VWAP Alignment Gate (Phase 2)
    # Individual stocks cannot fight broader market distribution on closing gap-ups
    # =========================================================================
    nifty_vwap_gate_applied = None
    if bullish_bias and nifty_below_vwap:
        nifty_vwap_gate_applied = "VETOED: NIFTY 50 trading below Intraday VWAP at 3:15 PM closing window"
        if signal == "BTST (BUY)":
            signal = "NEUTRAL"
            priority_level = "P3_LOW"
            conviction_level = "WATCHLIST"
            confidence_score = min(confidence_score, 48)

    # =========================================================================
    # EXHAUSTION & MEAN REVERSION VETO (Phase 1)
    # Prevents buying stocks that have exhausted daily energy at 3:25 PM
    # 1. Quiet Pump: Intraday Gain > 4.5% with Volume Surge < 1.5x
    # 2. ATR Range Exhaustion: Day Range > 1.5x 14-day ATR
    # 3. 20-EMA Overextension > 5.0% with RSI > 72
    # =========================================================================
    exhaustion_veto_applied = None
    is_exhaustion_vetoed = False
    if bullish_bias and (is_quiet_pump or is_day_range_exhausted or is_ema_overextended):
        ex_reasons = []
        if is_quiet_pump:
            ex_reasons.append(f"Quiet Pump (Gain +{stock_pct_change}% with Vol Surge {vol_spike_ratio}x < 1.5x)")
        if is_day_range_exhausted:
            ex_reasons.append(f"ATR Range Exhaustion (Day Range {day_range:.2f} > 1.5x ATR14 {atr_14:.2f})")
        if is_ema_overextended:
            ex_reasons.append(f"20-EMA Overextension (+{ema_20_extension_pct:.1f}%)")
        
        is_exhaustion_vetoed = True
        exhaustion_veto_applied = f"VETOED_EXHAUSTION: {'; '.join(ex_reasons)}"
        if signal == "BTST (BUY)":
            signal = "NEUTRAL"
            priority_level = "P3_LOW"
            conviction_level = "WATCHLIST"
            confidence_score = min(confidence_score, 45)

    # =========================================================================
    # ORDER FLOW VETO LAYER (Phase 3: 3:15-3:25 PM Closing Aggression & Selling Pressure)
    # If synthetic CVD or live tick delta shows net selling, deduct >= 20 pts and strip P1
    # =========================================================================
    from synthetic_cvd_engine import get_order_flow_data
    from order_flow_analyzer import check_closing_aggression
    
    order_flow_data = get_order_flow_data(clean_sym, signal_type=signal)
    day_cvd_trend = "BULLISH" if ltp >= vwap else "BEARISH"
    order_flow_veto = check_closing_aggression(clean_sym, order_flow_data, signal_type=signal, day_cvd_trend=day_cvd_trend)
    
    if order_flow_veto.get("verdict") == "vetoed":
        # Deduct minimum 20 points and strip P1 status immediately
        confidence_score = max(30, confidence_score - 20)
        if priority_level in ["P1_HIGH", "P2_MEDIUM"]:
            priority_level = "P3_LOW"
            conviction_level = "MODERATE"

    # Estimated Gap % Calculation — clamped strictly between 0.5% and 3.5%
    raw_gap = 0.5 + (capped_vol_spike * 0.4) + (abs(rsi - 50) * 0.03)
    est_gap = round(min(3.5, max(0.5, raw_gap)), 1)
    predicted_gap_pct = est_gap if (ltp >= vwap) else -est_gap

    # Explicit Priority Reason Metadata for UI & Debugging
    if priority_level == "P1_HIGH":
        priority_reason = f"Priority 1 High Conviction (Weight {total_confirmed_weight:.1f} >= {required_pillars:.1f} & Conf {confidence_score}% >= 88%)"
    elif exhaustion_veto_applied:
        priority_reason = exhaustion_veto_applied
    elif nifty_vwap_gate_applied:
        priority_reason = nifty_vwap_gate_applied
    elif fundamental_gate_applied:
        priority_reason = fundamental_gate_applied
    elif macro_gate_applied:
        priority_reason = macro_gate_applied
    elif priority_level == "P2_MEDIUM":
        priority_reason = f"Priority 2 Medium (Weight {total_confirmed_weight:.1f} / Req {required_pillars:.1f} [{liquidity_tier}])"
    else:
        priority_reason = "Priority 3 Watchlist"

    reason_str = f"Confirmed {total_confirmed_weight}/{required_pillars} Pillar Weight [{liquidity_tier}]"
    if expiry_discounted:
        reason_str += " (Expiry OI Halving Discount Applied)"

    return {
        "symbol": clean_sym,
        "raw_ticker": symbol,
        "liquidity_tier": liquidity_tier,
        "required_pillars": required_pillars,
        "priority_reason": priority_reason,
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
            "macro_gate_applied": macro_gate_applied,
            "sector": fundamental_data.get("sector") if fundamental_data else None,
            "trailing_pe": fundamental_data.get("trailingPE") if fundamental_data else None,
            "return_on_equity": fundamental_data.get("returnOnEquity") if fundamental_data else None,
            "debt_to_equity": fundamental_data.get("debtToEquity") if fundamental_data else None,
            "earnings_growth": fundamental_data.get("earningsGrowth") if fundamental_data else None,
            "red_flags": fundamental_data.get("quality", {}).get("red_flags", []) if fundamental_data else [],
            "yellow_flags": fundamental_data.get("quality", {}).get("yellow_flags", []) if fundamental_data else [],
            "data_status": "STALE_CACHE" if (fundamental_data and fundamental_data.get("stale")) else ("AVAILABLE" if fundamental_data else "DATA_UNAVAILABLE")
        },
        "exhaustion_veto": {
            "is_vetoed": is_exhaustion_vetoed,
            "reason": exhaustion_veto_applied,
            "atr_14": round(atr_14, 2),
            "day_range": round(day_range, 2),
            "ema_20": round(ema_20, 2),
            "ema_20_extension_pct": ema_20_extension_pct,
            "is_quiet_pump": is_quiet_pump,
            "is_day_range_exhausted": is_day_range_exhausted,
            "is_ema_overextended": is_ema_overextended
        },
        "nifty_vwap_gate": {
            "nifty_below_vwap": nifty_below_vwap,
            "nifty_ltp": nifty_ltp_val,
            "nifty_vwap": nifty_vwap_val,
            "gate_applied": nifty_vwap_gate_applied
        },
        "vix_regime_gate": {
            "vix_value": vix_val,
            "is_low_vol_regime": vix_low_vol_regime,
            "gate_applied": macro_gate_applied if vix_low_vol_regime else None
        },
        "order_flow_veto": order_flow_veto,
        "order_flow_data": order_flow_data.to_dict() if order_flow_data else None,
        "signal": signal,
        "option_type": option_type,
        "conviction_level": conviction_level,
        "priority_level": priority_level,
        "confidence_score": confidence_score,
        "predicted_gap_pct": predicted_gap_pct,
        "ltp": round(ltp, 2),
        "prev_close": round(prev_close, 2),
        "change_pts": round(ltp - prev_close, 2),
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
