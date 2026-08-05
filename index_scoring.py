"""
INDEX SIGNAL MODEL — Nifty 50, Bank Nifty, Sensex
====================================================
Indices are NOT scored with the stock 5-pillar matrix. That matrix leans on per-stock
volume (persistence, spike) and a volume-weighted VWAP — and yfinance reports Volume=0 for
all three indices (verified empirically): an index isn't itself traded, only its
constituents/derivatives are, so there's no per-tick volume to report against the index
print. Forcing the stock matrix onto zero-volume data would silently degenerate — VWAP
collapses to the plain close price, and 2 of the 5 pillars could never confirm — so this is
a dedicated, honestly-scoped model built around what's actually computable for an index:

1. Marubozu-style close position (pure OHLC — same concept as the stock matrix's Pillar 5)
2. Relative Strength vs Nifty 50 (Bank Nifty / Sensex only — Nifty compared to itself is
   meaningless, so this pillar is DATA_UNAVAILABLE for Nifty itself, not faked)
3. Global Cues — US markets overnight (Dow, Nasdaq), Asian markets same-day (Nikkei, Hang
   Seng), USD/INR, and crude oil: the standard pre-market checklist Indian traders use to
   gauge how the local market is likely to open/trend. This is what makes it a "global"
   read, not just a domestic technical one.
4. Macro news sentiment — reuses news_provider's market-news channel (same transparent
   keyword-flag discipline as the stock news gate: every flag traces to a headline).

Same discipline as the rest of this codebase: FAIL LOUD (missing data excluded, never
fabricated), gates only cap conviction they don't invent it, and every pillar's weight can be
driven by a strategy config (pillar_weight_multipliers) — see strategy_manager.py.
"""

import logging
from typing import Dict, Any, Optional

import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger("IndexScoring")

INDEX_TICKERS: Dict[str, str] = {
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
}

GLOBAL_CUE_TICKERS: Dict[str, str] = {
    "DOW": "^DJI",
    "NASDAQ": "^IXIC",
    "NIKKEI": "^N225",
    "HANGSENG": "^HSI",
    "CRUDE": "CL=F",
    "USDINR": "INR=X",
}

# Indices have fewer independently-computable pillars than stocks (no volume-based ones survive
# zero-volume index data), so the bar is proportionally lower — not a laxer standard, a smaller
# denominator. Nifty itself tops out at 3.0 possible (no RS-vs-self pillar); Bank Nifty/Sensex
# top out at 4.0.
REQUIRED_INDEX_WEIGHT = 2.0


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_global_cues() -> Optional[Dict[str, float]]:
    """
    Latest daily % change for each global-cue ticker. Returns None entirely on failure
    (FAIL LOUD) — never a partial/fabricated read standing in for missing data.
    """
    cues: Dict[str, float] = {}
    try:
        for name, ticker in GLOBAL_CUE_TICKERS.items():
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            df = _flatten_columns(df).dropna()
            if len(df) < 2:
                continue
            prev_close = float(df["Close"].iloc[-2])
            latest_close = float(df["Close"].iloc[-1])
            if prev_close <= 0:
                continue
            cues[name] = round(((latest_close - prev_close) / prev_close) * 100, 2)
    except Exception as e:
        logger.warning(f"Global cues fetch failed: {e}")
        return None

    return cues if cues else None


def classify_global_cues(cues: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """
    US + Asian equities up = risk-on tailwind for Nifty. Crude oil up = headwind (India is a
    major net oil importer). INR weakening (USDINR up) = mild headwind (FII outflow pressure).
    This is a same-morning directional read of the standard checklist, not a prediction model.
    """
    if cues is None:
        return {"verdict": "UNAVAILABLE", "cues": {}, "bullish_count": 0, "bearish_count": 0}

    bullish_count = 0
    bearish_count = 0
    for name in ("DOW", "NASDAQ", "NIKKEI", "HANGSENG"):
        if name in cues:
            if cues[name] > 0.15:
                bullish_count += 1
            elif cues[name] < -0.15:
                bearish_count += 1
    if "CRUDE" in cues:
        if cues["CRUDE"] > 1.0:
            bearish_count += 1
        elif cues["CRUDE"] < -1.0:
            bullish_count += 1
    if "USDINR" in cues:
        if cues["USDINR"] > 0.3:
            bearish_count += 1
        elif cues["USDINR"] < -0.3:
            bullish_count += 1

    if bullish_count >= bearish_count + 2:
        verdict = "TAILWIND"
    elif bearish_count >= bullish_count + 2:
        verdict = "HEADWIND"
    else:
        verdict = "MIXED"

    return {"verdict": verdict, "cues": cues, "bullish_count": bullish_count, "bearish_count": bearish_count}


def evaluate_index_signal(
    index_name: str,
    df_index: pd.DataFrame,
    df_nifty: Optional[pd.DataFrame] = None,
    global_cues_read: Optional[Dict[str, Any]] = None,
    news_classification: Optional[Dict[str, Any]] = None,
    pillar_weight_multipliers: Optional[Dict[str, float]] = None,
    required_weight_override: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluate one index (NIFTY50 / BANKNIFTY / SENSEX) against the 4-pillar index model.

    df_index: intraday OHLC for the index itself (Volume ignored — always 0).
    df_nifty: intraday OHLC for Nifty 50, for the relative-strength pillar. Pass None for
    NIFTY50 itself (comparing Nifty to Nifty is meaningless, not computed).
    global_cues_read / news_classification: pass the ALREADY-COMPUTED, already-classified
    reads (see fetch_global_cues/classify_global_cues and news_provider's market-news
    channel) — this function doesn't fetch them itself so callers can share one fetch across
    all three indices per scan instead of tripling the network calls.
    required_weight_override: replaces REQUIRED_INDEX_WEIGHT — lets strategy_manager define a
    strategy-specific confirmation bar for indices, same mechanism as the stock matrix.
    """
    weight_mult = pillar_weight_multipliers or {}

    def _mult(pillar_name: str) -> float:
        return weight_mult.get(pillar_name, 1.0)

    if df_index is None or df_index.empty or len(df_index) < 5:
        return {
            "index_name": index_name,
            "required_weight": REQUIRED_INDEX_WEIGHT,
            "confirmed_pillars_weight": 0.0,
            "confirmed_pillars": [],
            "signal": "NEUTRAL",
            "reason": "Insufficient intraday data",
        }

    df_index = df_index.dropna(subset=["Close", "Open", "High", "Low"]).copy()
    latest = df_index.iloc[-1]
    session_open = float(df_index.iloc[0]["Open"])
    daily_high = float(df_index["High"].max())
    daily_low = float(df_index["Low"].min())
    ltp = float(latest["Close"])
    pct_change = round(((ltp - session_open) / session_open) * 100, 2)

    delta = df_index["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.fillna(50.0).iloc[-1])

    day_range = daily_high - daily_low
    range_position_pct = round(max(0.0, min(100.0, ((ltp - daily_low) / day_range) * 100.0)), 2) if day_range > 0 else 50.0

    # Bias: no VWAP available (needs volume) — price vs session open + RSI plays that role instead.
    bullish_bias = pct_change > 0.1 and rsi >= 55
    bearish_bias = pct_change < -0.1 and rsi <= 45

    confirmed_pillars = []
    pillar_weights: Dict[str, float] = {}

    # Pillar: Marubozu-style close position (direction-agnostic confirmation)
    p_marubozu_confirmed = (range_position_pct >= 98.0) or (range_position_pct <= 2.0)
    p_marubozu_weight = (1.0 * _mult("Index: Marubozu Close")) if p_marubozu_confirmed else 0.0
    if p_marubozu_confirmed:
        confirmed_pillars.append(f"Marubozu Close (Range Pos: {range_position_pct}%)")
    pillar_weights["Index: Marubozu Close"] = p_marubozu_weight

    # Pillar: Relative Strength vs Nifty 50 (Bank Nifty / Sensex only)
    p_rs_weight = 0.0
    rs_diff = None
    if index_name != "NIFTY50" and df_nifty is not None and not df_nifty.empty:
        n_open = float(df_nifty.iloc[0]["Open"])
        n_ltp = float(df_nifty.iloc[-1]["Close"])
        nifty_pct_change = round(((n_ltp - n_open) / n_open) * 100, 2)
        rs_diff = round(pct_change - nifty_pct_change, 2)
        if bullish_bias and rs_diff >= 0.15:
            p_rs_weight = 1.0 * _mult("Index: Relative Strength")
            confirmed_pillars.append(f"RS vs Nifty (Outperforming +{rs_diff}%)")
        elif bearish_bias and rs_diff <= -0.15:
            p_rs_weight = 1.0 * _mult("Index: Relative Strength")
            confirmed_pillars.append(f"RS vs Nifty (Underperforming {rs_diff}%)")
    pillar_weights["Index: Relative Strength"] = p_rs_weight

    # Pillar: Global Cues
    p_global_weight = 0.0
    global_verdict = "UNAVAILABLE"
    if global_cues_read is not None:
        global_verdict = global_cues_read.get("verdict", "UNAVAILABLE")
        if bullish_bias and global_verdict == "TAILWIND":
            p_global_weight = 1.0 * _mult("Index: Global Cues")
            confirmed_pillars.append("Global Cues: Tailwind (US/Asia + crude/INR supportive)")
        elif bearish_bias and global_verdict == "HEADWIND":
            p_global_weight = 1.0 * _mult("Index: Global Cues")
            confirmed_pillars.append("Global Cues: Headwind (US/Asia + crude/INR against)")
    pillar_weights["Index: Global Cues"] = p_global_weight

    # Pillar: Macro news sentiment
    p_news_weight = 0.0
    news_verdict = "UNAVAILABLE"
    if news_classification is not None:
        news_verdict = news_classification.get("verdict", "UNAVAILABLE")
        if bullish_bias and news_verdict == "POSITIVE":
            p_news_weight = 1.0 * _mult("Index: Macro News")
            confirmed_pillars.append("Macro News: Positive")
        elif bearish_bias and news_verdict == "NEGATIVE":
            p_news_weight = 1.0 * _mult("Index: Macro News")
            confirmed_pillars.append("Macro News: Negative")
    pillar_weights["Index: Macro News"] = p_news_weight

    total_confirmed_weight = round(sum(pillar_weights.values()), 2)
    required_weight = required_weight_override if required_weight_override is not None else REQUIRED_INDEX_WEIGHT

    signal = "NEUTRAL"
    option_type = "NONE"
    conviction_level = "WATCHLIST"
    is_valid_signal = total_confirmed_weight >= required_weight

    if is_valid_signal:
        high_conviction_bar = required_weight + 1.0
        if bullish_bias:
            signal = "BTST (BUY)"
            option_type = "CALL (CE)"
            conviction_level = "HIGH_CONVICTION" if total_confirmed_weight >= high_conviction_bar else "MODERATE"
        elif bearish_bias:
            signal = "STBT (SELL)"
            option_type = "PUT (PE)"
            conviction_level = "HIGH_CONVICTION" if total_confirmed_weight >= high_conviction_bar else "MODERATE"

    weight_ratio = total_confirmed_weight / required_weight if required_weight > 0 else 0.0
    base_score = int(50 + (weight_ratio * 35))
    if p_marubozu_confirmed:
        base_score += 5
    confidence_score = min(99, max(40, base_score))

    if signal in ("BTST (BUY)", "STBT (SELL)"):
        if confidence_score >= 90:
            priority_level = "P1_HIGH"
        elif confidence_score >= 75:
            priority_level = "P2_MEDIUM"
        else:
            priority_level = "P3_LOW"
    else:
        priority_level = "P3_LOW"

    est_gap = round(0.5 + (abs(rsi - 50) * 0.03), 2)
    predicted_gap_pct = est_gap if pct_change >= 0 else -est_gap

    return {
        "index_name": index_name,
        "raw_ticker": INDEX_TICKERS.get(index_name, index_name),
        "required_weight": required_weight,
        "confirmed_pillars_weight": total_confirmed_weight,
        "confirmed_pillars": confirmed_pillars,
        "pillar_weights": pillar_weights,
        "relative_strength": {"rs_diff": rs_diff, "data_status": "AVAILABLE" if rs_diff is not None else "N/A_FOR_NIFTY50" if index_name == "NIFTY50" else "DATA_UNAVAILABLE"},
        "global_cues": {"verdict": global_verdict, "detail": global_cues_read.get("cues", {}) if global_cues_read else {}},
        "macro_news": {"verdict": news_verdict},
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
        "rsi": round(rsi, 1),
        "pct_change": pct_change,
        "rank_reason": f"Confirmed {total_confirmed_weight}/{required_weight} Index Pillar Weight",
        "score": confidence_score,
    }
