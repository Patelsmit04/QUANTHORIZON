"""
INTRADAY STRATEGY ENGINE — 6 RULE-BASED CONDITION CHAINS + GLOBAL FILTERS
============================================================================
Long-only options-alert strategies (A-F from the spec). Each evaluate_* function is a pure
function of already-fetched data (OHLCV DataFrame + any pre-resolved extras like OI-change,
VIX, IV, event flags) — no network calls happen in here, matching smc_strategy.py's
evaluate_signal() contract, so every strategy is testable against synthetic DataFrames.

Each function returns None ("no setup") or a raw alert dict:
    {
        "strategy_key": "vwap_pullback", "strategy_name": "VWAP Pullback",
        "direction": "BULLISH"|"BEARISH"|"NEUTRAL", "option_type": "CE"|"PE"|"BOTH",
        "otm_steps": 0,                                  # 0 = ATM
        "target": Optional[float], "target_text": Optional[str],
        "stop_loss": Optional[float], "rationale": str,
    }
strategy_engine.py resolves this into strike/expiry (option_strike_utils.py), applies the
global filters below, dedups, and dispatches.

NEVER a sell/write recommendation — every strategy here only ever buys a call, a put, or
both (Strategy F). This is enforced by construction: no function below has a code path that
returns anything but BUY-side actions.
"""

import logging
from typing import Any, Dict, Optional

import pandas as pd

from indicator_utils import compute_vwap, compute_ema, compute_rsi, compute_bollinger_bands

logger = logging.getLogger("StrategyEngineRules")

# ---------------------------------------------------------------------------
# Global filters (applied centrally by strategy_engine.py, not duplicated per strategy)
# ---------------------------------------------------------------------------

VIX_CALL_MAX = 18.0   # spec: don't generate Buy Call alerts if India VIX > 18
VIX_PUT_MAX = 14.0    # spec: generate Buy Put alerts only if India VIX < 14
EOD_CUTOFF_HOUR = 14
EOD_CUTOFF_MINUTE = 45


def vix_gate(vix_value: Optional[float], direction_or_option_type: str) -> bool:
    """True if this VIX reading permits the given side. vix_value=None (VIX unavailable) is
    treated as a fail-closed block, not a silent pass-through — the spec's whole point is to
    keep users out of expensive/cheap-premium traps, and an unverified VIX can't confirm
    either side is safe."""
    if vix_value is None:
        return False

    side = direction_or_option_type.upper()
    wants_call = "CALL" in side or side == "CE" or side == "BULLISH"
    wants_put = "PUT" in side or side == "PE" or side == "BEARISH"

    if side == "BOTH":  # Strategy F buys a call AND a put — both gates must pass
        return vix_value <= VIX_CALL_MAX and vix_value < VIX_PUT_MAX
    if wants_call:
        return vix_value <= VIX_CALL_MAX
    if wants_put:
        return vix_value < VIX_PUT_MAX
    return False


def is_past_eod_cutoff(now) -> bool:
    """True once it's past 2:45 PM IST — no new alerts after this (spec's theta-decay
    protection)."""
    return (now.hour, now.minute) >= (EOD_CUTOFF_HOUR, EOD_CUTOFF_MINUTE)


# ---------------------------------------------------------------------------
# Strategy A: VWAP & EMA Pullback (Buy Call) — Nifty 50 / Sensex / Bank Nifty
# ---------------------------------------------------------------------------

def evaluate_vwap_pullback(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    if df is None or len(df) < 20:
        return None

    ema20 = compute_ema(df["Close"], span=20)
    vwap = compute_vwap(df)
    rsi = compute_rsi(df["Close"], period=14)
    _, upper_bb, _ = compute_bollinger_bands(df["Close"], period=20, std_mult=2)

    close_now = float(df["Close"].iloc[-1])
    ema_now = float(ema20.iloc[-1])
    vwap_now = float(vwap.iloc[-1])

    trend_ok = close_now > ema_now
    if not trend_ok:
        return None

    # Pullback trigger: price touched VWAP or EMA within the last ~15 minutes (3 candles).
    lookback = min(3, len(df))
    touched = (df["Low"].iloc[-lookback:] <= vwap.iloc[-lookback:]).any() or \
              (df["Low"].iloc[-lookback:] <= ema20.iloc[-lookback:]).any()
    if not touched:
        return None

    # Reversal confirmation
    reversal_ok = close_now > vwap_now and float(rsi.iloc[-2]) < 50 and float(rsi.iloc[-1]) > 50
    if not reversal_ok:
        return None

    return {
        "strategy_key": "vwap_pullback",
        "strategy_name": "VWAP Pullback",
        "direction": "BULLISH",
        "option_type": "CE",
        "otm_steps": 0,
        "target": round(float(upper_bb.iloc[-1]), 2),
        "target_text": None,
        "stop_loss": round(max(vwap_now, ema_now), 2),
        "rationale": f"Pulled back to VWAP/EMA and reversed — RSI crossed above 50 (now {rsi.iloc[-1]:.1f}), Close {close_now:.2f} > VWAP {vwap_now:.2f}.",
    }


# ---------------------------------------------------------------------------
# Strategy B: Breakdown & Volume Spike (Buy Put) — Nifty 50 / Sensex / Bank Nifty
# ---------------------------------------------------------------------------

def evaluate_breakdown_spike(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    if df is None or len(df) < 21:
        return None

    range_window = df.iloc[-16:-1]  # 15 candles preceding the current one
    range_high = float(range_window["High"].max())
    range_low = float(range_window["Low"].min())
    if range_low <= 0:
        return None

    range_tight = (range_high - range_low) / range_low < 0.005
    if not range_tight:
        return None

    close_now = float(df["Close"].iloc[-1])
    breakdown = close_now < range_low
    if not breakdown:
        return None

    vol_baseline = float(df["Volume"].iloc[-6:-1].mean())
    vol_now = float(df["Volume"].iloc[-1])
    if vol_baseline <= 0 or vol_now <= 1.5 * vol_baseline:
        return None  # no real volume feed (e.g. index via yfinance) or no spike — don't fire

    projected_range = range_high - range_low
    return {
        "strategy_key": "breakdown_spike",
        "strategy_name": "Breakdown Spike",
        "direction": "BEARISH",
        "option_type": "PE",
        "otm_steps": 0,
        "target": round(range_low - projected_range, 2),
        "target_text": None,
        "stop_loss": round(range_low, 2),
        "volume_spike_ratio": round(vol_now / vol_baseline, 2),
        "rationale": f"Broke below the 15-candle consolidation low {range_low:.2f} (range high {range_high:.2f}) on {vol_now / vol_baseline:.1f}x volume.",
    }


# ---------------------------------------------------------------------------
# Strategy C: Opening Range Breakout (bi-directional) — all indices
# ---------------------------------------------------------------------------

def compute_orb_levels(df_session: pd.DataFrame, session_date) -> Optional[Dict[str, float]]:
    """First 30 minutes (9:15-9:45 AM IST) High/Low for the given session date, from a 5-min
    intraday DataFrame spanning at least that morning. Returns None if the opening window
    isn't present in df_session (e.g. called before 9:45 or on a day with no data)."""
    day_rows = df_session[df_session.index.date == session_date]
    if day_rows.empty:
        return None
    opening_window = day_rows.between_time("09:15", "09:44")
    if opening_window.empty:
        return None
    return {"orb_high": float(opening_window["High"].max()), "orb_low": float(opening_window["Low"].min())}


def evaluate_orb(df: pd.DataFrame, orb_high: float, orb_low: float) -> Optional[Dict[str, Any]]:
    """Caller (strategy_engine.py) computes orb_high/orb_low once per session via
    compute_orb_levels() and passes them in, and is responsible for the spec's "triggers once
    per day" rule — that's day-level state, not something a pure per-tick function can track."""
    if df is None or len(df) < 2 or orb_high is None or orb_low is None:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    if float(latest["High"]) > orb_high:
        projected = orb_high - orb_low
        return {
            "strategy_key": "orb",
            "strategy_name": "ORB",
            "direction": "BULLISH",
            "option_type": "CE",
            "otm_steps": 0,
            "target": round(orb_high + projected, 2),
            "target_text": None,
            "stop_loss": round(float(prev["Low"]), 2),
            "rationale": f"Broke above the opening range high {orb_high:.2f} (9:15-9:45 AM range).",
        }

    if float(latest["Low"]) < orb_low:
        projected = orb_high - orb_low
        return {
            "strategy_key": "orb",
            "strategy_name": "ORB",
            "direction": "BEARISH",
            "option_type": "PE",
            "otm_steps": 0,
            "target": round(orb_low - projected, 2),
            "target_text": None,
            "stop_loss": round(float(prev["High"]), 2),
            "rationale": f"Broke below the opening range low {orb_low:.2f} (9:15-9:45 AM range).",
        }

    return None


# ---------------------------------------------------------------------------
# Strategy D: Surge & OI Build-up (Buy Call, 1-strike OTM) — All F&O stocks
# ---------------------------------------------------------------------------

def evaluate_oi_surge(df: pd.DataFrame, oi_change_15min: Optional[float]) -> Optional[Dict[str, Any]]:
    if df is None or len(df) < 4 or oi_change_15min is None:
        return None

    close_now = float(df["Close"].iloc[-1])
    close_15min_ago = float(df["Close"].iloc[-4])
    open_breakout_candle = float(df["Open"].iloc[-4])
    if close_15min_ago <= 0:
        return None

    price_change_pct = (close_now - close_15min_ago) / close_15min_ago * 100.0
    if price_change_pct <= 2.0:
        return None
    if oi_change_15min <= 0:
        return None  # no long build-up

    rsi = compute_rsi(df["Close"], period=14)
    rsi_now = float(rsi.iloc[-1])
    if not (55.0 <= rsi_now <= 75.0):
        return None

    return {
        "strategy_key": "oi_surge",
        "strategy_name": "OI Surge",
        "direction": "BULLISH",
        "option_type": "CE",
        "otm_steps": 1,
        "target": None,
        "target_text": "Book 50% of position when premium doubles; book remaining when RSI > 78.",
        "stop_loss": round(open_breakout_candle, 2),
        "rationale": f"+{price_change_pct:.1f}% in 15 min with OI up {oi_change_15min:.1f}% (long build-up), RSI {rsi_now:.1f}.",
    }


# ---------------------------------------------------------------------------
# Strategy E: Death Cross & OI Surge (Buy Put) — All F&O stocks, 15-min timeframe
# ---------------------------------------------------------------------------

def evaluate_death_cross(df_15m: pd.DataFrame, oi_change_15min: Optional[float]) -> Optional[Dict[str, Any]]:
    if df_15m is None or len(df_15m) < 22 or oi_change_15min is None:
        return None

    ema5 = compute_ema(df_15m["Close"], span=5)
    ema20 = compute_ema(df_15m["Close"], span=20)

    crossed_below = float(ema5.iloc[-2]) >= float(ema20.iloc[-2]) and float(ema5.iloc[-1]) < float(ema20.iloc[-1])
    if not crossed_below:
        return None

    close_now = float(df_15m["Close"].iloc[-1])
    close_prev = float(df_15m["Close"].iloc[-2])
    if close_prev <= 0:
        return None
    price_change_pct = (close_now - close_prev) / close_prev * 100.0

    if not (oi_change_15min > 0 and price_change_pct < 0):
        return None  # not a short build-up

    swing_low_window = df_15m.iloc[-30:-3] if len(df_15m) >= 33 else df_15m.iloc[:-3]
    swing_low = float(swing_low_window["Low"].min()) if not swing_low_window.empty else None

    return {
        "strategy_key": "death_cross",
        "strategy_name": "Death Cross",
        "direction": "BEARISH",
        "option_type": "PE",
        "otm_steps": 0,
        "target": round(swing_low, 2) if swing_low else None,
        "target_text": None if swing_low else "Next major support level.",
        "stop_loss": round(float(ema5.iloc[-1]), 2),
        "rationale": f"5-EMA crossed below 20-EMA (15m) with OI up {oi_change_15min:.1f}% and price down {price_change_pct:.1f}% (short build-up).",
    }


# ---------------------------------------------------------------------------
# Strategy F: Volatility Straddle (Buy Call + Buy Put) — Indices & Stocks
# ---------------------------------------------------------------------------

def evaluate_volatility_straddle(is_in_lower_iv_percentile: Optional[bool], has_event_within_48h: bool) -> Optional[Dict[str, Any]]:
    """is_in_lower_iv_percentile: from iv_history_tracker.is_in_lower_iv_percentile() —
    None (not enough IV history yet) is treated as "no setup", same FAIL LOUD discipline as
    every other unresolved data read in this codebase."""
    if is_in_lower_iv_percentile is not True or not has_event_within_48h:
        return None

    return {
        "strategy_key": "volatility_straddle",
        "strategy_name": "Volatility Straddle",
        "direction": "NEUTRAL",
        "option_type": "BOTH",
        "otm_steps": 0,
        "target": None,
        "target_text": "Hold both legs through the event; exit both within the first 15 minutes of the next session's open.",
        "stop_loss": None,
        "rationale": "IV in the lower 10th percentile of its 20-day range with a high-impact event within 48 hours.",
    }
