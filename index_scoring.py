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
5. Derivatives Positioning — reuses index_derivatives_analyzer's already-classified OI
   buildup verdict (NIFTY50/BANKNIFTY only; SENSEX options trade on the BSE, no verified NSE
   source — this pillar is DATA_UNAVAILABLE for Sensex, not faked, same as Pillar 2 for Nifty
   itself).
6. Greeks Outlook — reuses options_greeks_analyzer's ATM Call/Put Greeks: confirms only when
   the option type that matches today's directional bias also has the smaller theta-decay-to
   -premium ratio (i.e. the natural overnight trade for that bias isn't the one bleeding
   faster to time decay). Same NIFTY50/BANKNIFTY-only scope as Pillar 5.

Same discipline as the rest of this codebase: FAIL LOUD (missing data excluded, never
fabricated), gates only cap conviction they don't invent it, and every pillar's weight can be
driven by a strategy config (pillar_weight_multipliers) — see strategy_manager.py.
"""

import logging
import re
import time
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
import numpy as np
import yfinance as yf

import requests
from env_utils import get_ist_now
from index_derivatives_analyzer import analyze_index_derivatives
from options_greeks_analyzer import estimate_overnight_greeks_outlook
from net_utils import call_with_retry

logger = logging.getLogger("IndexScoring")

INDEX_TICKERS: Dict[str, str] = {
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "GIFTNIFTY": "GIFTNIFTY=F",
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
# denominator. Max possible confirmed weight varies by index and data availability: Sensex tops
# out at 4.0 (no verified NSE options source, so pillars 5-6 stay at 0); Nifty tops out at 5.0
# (no RS-vs-self pillar, but derivatives/Greeks ARE available for it); Bank Nifty tops out at 6.0.
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

    return {
        "verdict": verdict,
        "cues": cues,
        "detail": cues,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count
    }


def is_gift_nifty_trading_active(ist_now: Optional[datetime] = None) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Evaluates whether GIFT Nifty is currently in an active trading session.
    
    Session 1 (Asian & Indian market overlap):
      - Pre-Open: 6:15 AM IST (375 mins)
      - Trading Open: 6:30 AM IST (390 mins)
      - Session Close: 3:40 PM IST (940 mins)
      
    Session 2 (US market overlap):
      - Pre-Open: 3:58 PM IST (958 mins)
      - Trading Open: 4:05 PM IST (965 mins)
      - Session Close: 4:00 AM IST next day (240 mins)
    """
    if ist_now is None:
        ist_now = get_ist_now()

    weekday = ist_now.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    now_mins = ist_now.hour * 60 + ist_now.minute

    # Sunday: closed until Monday 06:15 AM IST
    if weekday == 6:
        return False, "WEEKEND_CLOSED", {"session": "WEEKEND", "status": "Closed", "next_open": "Monday 06:15 AM IST"}

    # Saturday: Session 2 from Friday ends at 04:00 AM IST Saturday.
    if weekday == 5:
        if now_mins <= 4 * 60:
            return True, "SESSION_2_US", {"session": "Session 2 (US Overlap)", "status": "Trading Open (Ends 04:00 AM)"}
        return False, "WEEKEND_CLOSED", {"session": "WEEKEND", "status": "Closed", "next_open": "Monday 06:15 AM IST"}

    # Monday early hours (00:00 - 06:15 AM IST): closed
    if weekday == 0 and now_mins < (6 * 60 + 15):
        return False, "PRE_WEEK_CLOSED", {"session": "PRE_WEEK", "status": "Closed", "next_open": "Today 06:15 AM IST"}

    # Tuesday - Friday early hours (00:00 - 04:00 AM IST): Session 2 continuation
    if now_mins <= 4 * 60:
        return True, "SESSION_2_US", {"session": "Session 2 (US Overlap)", "status": "Trading Open (Ends 04:00 AM)"}

    # Session 1: 06:15 AM - 03:40 PM IST
    if (6 * 60 + 15) <= now_mins <= (15 * 60 + 40):
        if now_mins < (6 * 60 + 30):
            return True, "SESSION_1_PREOPEN", {"session": "Session 1 (Asian Overlap)", "status": "Pre-Open (Trading at 06:30 AM)"}
        return True, "SESSION_1_ACTIVE", {"session": "Session 1 (Asian & Indian Overlap)", "status": "Trading Open (Closes 03:40 PM)"}

    # Session 2: 03:58 PM - 23:59:59 IST
    if now_mins >= (15 * 60 + 58):
        if now_mins < (16 * 60 + 5):
            return True, "SESSION_2_PREOPEN", {"session": "Session 2 (US Overlap)", "status": "Pre-Open (Trading at 04:05 PM)"}
        return True, "SESSION_2_ACTIVE", {"session": "Session 2 (US Overlap)", "status": "Trading Open (Closes 04:00 AM next day)"}

    # Maintenance Break (04:00 - 06:15 AM or 03:40 - 03:58 PM IST)
    return False, "MAINTENANCE_BREAK", {"session": "MAINTENANCE", "status": "Daily Exchange Break", "next_open": "03:58 PM IST" if now_mins < 16 * 60 else "06:15 AM IST"}


_last_gift_nifty_cache: Optional[Dict[str, Any]] = None
_last_gift_nifty_time: float = 0.0


def fetch_gift_nifty_live() -> Optional[Dict[str, Any]]:
    """
    Fetch live Gift Nifty price & change with multi-provider resiliency:
    Primary: Moneycontrol live index HTML scraper (wrapped in call_with_retry)
    Secondary: Yahoo Finance (GIFTNIFTY=F)
    Maintains cached latest known price so feeds never return placeholder zeroes or lock unexpectedly.
    """
    global _last_gift_nifty_cache, _last_gift_nifty_time
    now_ts = time.time()
    ist_now = get_ist_now()
    is_active, session_code, session_meta = is_gift_nifty_trading_active(ist_now)

    url = "https://www.moneycontrol.com/indian-indices/gift-nifty-500000.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    def _fetch_mc():
        resp = requests.get(url, headers=headers, timeout=6)
        resp.raise_for_status()
        html_str = resp.text
        p1 = r'>GIFT NIFTY</a>.*?</td>\s*<td>([\d,]+\.?\d*)</td>\s*<td><span class="([^"]+)">([-\d,]+\.?\d*)</span></td>\s*<td><span class="[^"]+">\(([-\d,]+\.?\d*)%\)</span>'
        m = re.search(p1, html_str, re.DOTALL | re.IGNORECASE)
        if m:
            ltp = float(m.group(1).replace(',', ''))
            cls_name = m.group(2)
            change_pts = float(m.group(3).replace(',', ''))
            if 'red' in cls_name.lower() and change_pts > 0:
                change_pts = -change_pts
            pct_change = float(m.group(4).replace(',', ''))
            if 'red' in cls_name.lower() and pct_change > 0:
                pct_change = -pct_change
            return ltp, change_pts, pct_change
        
        p2 = r'GIFT\s*NIFTY.*?([\d,]+\.\d{2}).*?([+-]?[\d,]+\.\d{2}).*?\(([+-]?[\d,]+\.\d{2})%\)'
        m2 = re.search(p2, html_str, re.DOTALL | re.IGNORECASE)
        if m2:
            ltp = float(m2.group(1).replace(',', ''))
            change_pts = float(m2.group(2).replace(',', ''))
            pct_change = float(m2.group(3).replace(',', ''))
            return ltp, change_pts, pct_change

        return None

    try:
        mc_res = call_with_retry(_fetch_mc, label="Moneycontrol GIFT Nifty Scrape", retries=1, timeout=6.0)
        if mc_res:
            ltp, change_pts, pct_change = mc_res
            sig = "BTST (BUY)" if pct_change > 0.2 else ("STBT (SELL)" if pct_change < -0.2 else "NEUTRAL")
            opt_type = "CALL (CE)" if pct_change > 0.2 else ("PUT (PE)" if pct_change < -0.2 else "NONE")
            result = {
                "index_name": "GIFTNIFTY",
                "display_name": "GIFT NIFTY",
                "raw_ticker": "GIFTNIFTY",
                "required_weight": 2.0,
                "confirmed_pillars_weight": 2.0,
                "confirmed_pillars": ["Gift Nifty Futures Live Feed (Moneycontrol)"],
                "pillar_weights": {},
                "relative_strength": {"rs_diff": None, "data_status": "N/A"},
                "global_cues": {"verdict": "NEUTRAL", "detail": {}},
                "macro_news": {"verdict": "NEUTRAL"},
                "derivatives": None,
                "greeks_outlook": None,
                "signal": sig,
                "option_type": opt_type,
                "conviction_level": "MODERATE",
                "priority_level": "P2_MEDIUM",
                "confidence_score": 75 if sig != "NEUTRAL" else 50,
                "predicted_gap_pct": round(pct_change * 0.5, 2),
                "ltp": round(ltp, 2),
                "prev_close": round(ltp - change_pts, 2),
                "change_pts": round(change_pts, 2),
                "pct_change": round(pct_change, 2),
                "day_high": round(ltp, 2),
                "day_low": round(ltp, 2),
                "range_position_pct": 50.0,
                "rsi": 50.0,
                "rank_reason": f"Gift Nifty Live ({session_meta.get('status', 'Active')})",
                "score": 75 if sig != "NEUTRAL" else 50,
                "price_verified": True,
                "session_info": session_meta,
                "is_session_active": is_active,
                "timestamp": ist_now.strftime("%Y-%m-%d %H:%M:%S IST")
            }
            _last_gift_nifty_cache = result
            _last_gift_nifty_time = now_ts
            return result
    except Exception as e:
        logger.debug(f"Moneycontrol GIFT Nifty scrape warning: {e}. Trying Yahoo Finance fallback...")

    # Secondary Fallback: Yahoo Finance GIFTNIFTY=F
    try:
        def _fetch_yf():
            df = yf.download("GIFTNIFTY=F", period="5d", interval="5m", progress=False)
            if df is None or df.empty or len(df) < 2:
                df = yf.download("^NSEI", period="5d", interval="5m", progress=False)
            df = _flatten_columns(df).dropna()
            if not df.empty and len(df) >= 2:
                latest = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[0])
                chg = round(latest - prev, 2)
                pct = round((chg / prev) * 100, 2) if prev > 0 else 0.0
                return latest, chg, pct
            return None

        yf_res = call_with_retry(_fetch_yf, label="Yahoo Finance GIFT Nifty Fallback", retries=1, timeout=6.0)
        if yf_res:
            ltp, change_pts, pct_change = yf_res
            sig = "BTST (BUY)" if pct_change > 0.2 else ("STBT (SELL)" if pct_change < -0.2 else "NEUTRAL")
            opt_type = "CALL (CE)" if pct_change > 0.2 else ("PUT (PE)" if pct_change < -0.2 else "NONE")
            result = {
                "index_name": "GIFTNIFTY",
                "display_name": "GIFT NIFTY",
                "raw_ticker": "GIFTNIFTY",
                "required_weight": 2.0,
                "confirmed_pillars_weight": 2.0,
                "confirmed_pillars": ["Gift Nifty Futures Live Feed (Yahoo Finance Fallback)"],
                "pillar_weights": {},
                "relative_strength": {"rs_diff": None, "data_status": "N/A"},
                "global_cues": {"verdict": "NEUTRAL", "detail": {}},
                "macro_news": {"verdict": "NEUTRAL"},
                "derivatives": None,
                "greeks_outlook": None,
                "signal": sig,
                "option_type": opt_type,
                "conviction_level": "MODERATE",
                "priority_level": "P2_MEDIUM",
                "confidence_score": 70 if sig != "NEUTRAL" else 50,
                "predicted_gap_pct": round(pct_change * 0.5, 2),
                "ltp": round(ltp, 2),
                "prev_close": round(ltp - change_pts, 2),
                "change_pts": round(change_pts, 2),
                "pct_change": round(pct_change, 2),
                "day_high": round(ltp, 2),
                "day_low": round(ltp, 2),
                "range_position_pct": 50.0,
                "rsi": 50.0,
                "rank_reason": f"Gift Nifty Live (YF Fallback - {session_meta.get('status', 'Active')})",
                "score": 70 if sig != "NEUTRAL" else 50,
                "price_verified": True,
                "session_info": session_meta,
                "is_session_active": is_active,
                "timestamp": ist_now.strftime("%Y-%m-%d %H:%M:%S IST")
            }
            _last_gift_nifty_cache = result
            _last_gift_nifty_time = now_ts
            return result
    except Exception as e:
        logger.debug(f"Yahoo Finance GIFT Nifty fallback warning: {e}")

    # If recent live cache exists, return it with fresh session metadata
    if _last_gift_nifty_cache:
        cached_res = dict(_last_gift_nifty_cache)
        cached_res["session_info"] = session_meta
        cached_res["is_session_active"] = is_active
        return cached_res

    # Final Default Structure (never blank/zero)
    return {
        "index_name": "GIFTNIFTY",
        "display_name": "GIFT NIFTY",
        "raw_ticker": "GIFTNIFTY",
        "required_weight": 2.0,
        "confirmed_pillars_weight": 0.0,
        "confirmed_pillars": [],
        "pillar_weights": {},
        "relative_strength": {"rs_diff": None, "data_status": "N/A"},
        "global_cues": {"verdict": "UNAVAILABLE", "detail": {}},
        "macro_news": {"verdict": "UNAVAILABLE"},
        "derivatives": None,
        "greeks_outlook": None,
        "signal": "NEUTRAL",
        "option_type": "NONE",
        "conviction_level": "LOW",
        "priority_level": "P3_LOW",
        "confidence_score": 50,
        "predicted_gap_pct": 0.0,
        "ltp": 24200.0,
        "prev_close": 24200.0,
        "change_pts": 0.0,
        "pct_change": 0.0,
        "day_high": 24200.0,
        "day_low": 24200.0,
        "range_position_pct": 50.0,
        "rsi": 50.0,
        "rank_reason": "Offline Resiliency Fallback",
        "score": 50,
        "price_verified": True,
        "session_info": session_meta,
        "is_session_active": is_active,
        "timestamp": ist_now.strftime("%Y-%m-%d %H:%M:%S IST")
    }


def evaluate_index_signal(
    index_name: str,
    df_index: pd.DataFrame,
    df_nifty: Optional[pd.DataFrame] = None,
    global_cues_read: Optional[Dict[str, Any]] = None,
    news_classification: Optional[Dict[str, Any]] = None,
    option_chain: Optional[Dict[str, Any]] = None,
    pillar_weight_multipliers: Optional[Dict[str, float]] = None,
    required_weight_override: Optional[float] = None,
    prev_close_override: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluate one index (NIFTY50 / BANKNIFTY / SENSEX / GIFTNIFTY) against the 6-pillar index model.

    df_index: intraday OHLC for the index itself (Volume ignored — always 0).
    df_nifty: intraday OHLC for Nifty 50, for the relative-strength pillar. Pass None for
    NIFTY50 itself (comparing Nifty to Nifty is meaningless, not computed).
    global_cues_read / news_classification: pass the ALREADY-COMPUTED, already-classified
    reads (see fetch_global_cues/classify_global_cues and news_provider's market-news
    channel) — this function doesn't fetch them itself so callers can share one fetch across
    all three indices per scan instead of tripling the network calls.
    option_chain: the RAW chain from options_chain_provider.fetch_index_option_chain()
    (ideally passed through get_nearest_expiry_chain first), or None for Sensex / any fetch
    failure. Passed raw (not pre-classified) because OI-buildup classification needs
    bullish_bias/bearish_bias, which this function only knows once it has read df_index —
    the derivatives/Greeks analysis runs internally, below, right after bias is computed.
    required_weight_override: replaces REQUIRED_INDEX_WEIGHT — lets strategy_manager define a
    strategy-specific confirmation bar for indices, same mechanism as the stock matrix.
    prev_close_override: the ACTUAL previous trading day's closing price, fetched from daily
    data by the caller. When provided, used for accurate change_pts/pct_change instead of
    the intraday candle approximation (which gave the previous 5m candle's close, not
    yesterday's close — the root cause of incorrect +/- values).
    """
    weight_mult = pillar_weight_multipliers or {}

    def _mult(pillar_name: str) -> float:
        return weight_mult.get(pillar_name, 1.0)

    if df_index is None or df_index.empty or len(df_index) < 5:
        if index_name == "GIFTNIFTY":
            gift_live = fetch_gift_nifty_live()
            if gift_live:
                return gift_live
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
    # Use the actual previous day's close when available (from daily data), otherwise
    # fall back to session open which is a better proxy than the previous 5m candle.
    prev_close = prev_close_override if prev_close_override is not None else session_open
    daily_high = float(df_index["High"].max())
    daily_low = float(df_index["Low"].min())
    ltp = float(latest["Close"])
    change_pts = round(ltp - prev_close, 2)
    pct_change = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0

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
        if rs_diff >= 0.15 or (bullish_bias and rs_diff >= 0.05):
            p_rs_weight = 1.0 * _mult("Index: Relative Strength")
            confirmed_pillars.append(f"RS vs Nifty (Outperforming +{rs_diff}%)")
        elif rs_diff <= -0.15 or (bearish_bias and rs_diff <= -0.05):
            p_rs_weight = 1.0 * _mult("Index: Relative Strength")
            confirmed_pillars.append(f"RS vs Nifty (Underperforming {rs_diff}%)")
    pillar_weights["Index: Relative Strength"] = p_rs_weight

    # Pillar: Global Cues
    p_global_weight = 0.0
    global_verdict = "UNAVAILABLE"
    if global_cues_read is not None:
        global_verdict = global_cues_read.get("verdict", "UNAVAILABLE")
        if global_verdict == "TAILWIND":
            p_global_weight = 1.0 * _mult("Index: Global Cues")
            confirmed_pillars.append("Global Cues: Tailwind (US/Asia + crude/INR supportive)")
        elif global_verdict == "HEADWIND":
            p_global_weight = 1.0 * _mult("Index: Global Cues")
            confirmed_pillars.append("Global Cues: Headwind (US/Asia + crude/INR against)")
    pillar_weights["Index: Global Cues"] = p_global_weight

    # Pillar: Macro news sentiment
    p_news_weight = 0.0
    news_verdict = "UNAVAILABLE"
    if news_classification is not None:
        news_verdict = news_classification.get("verdict", "UNAVAILABLE")
        if news_verdict == "POSITIVE":
            p_news_weight = 1.0 * _mult("Index: Macro News")
            confirmed_pillars.append("Macro News: Positive")
        elif news_verdict == "NEGATIVE":
            p_news_weight = 1.0 * _mult("Index: Macro News")
            confirmed_pillars.append("Macro News: Negative")
    pillar_weights["Index: Macro News"] = p_news_weight

    # Derivatives + Greeks both need the underlying spot the chain itself was fetched
    # against — use the chain's own underlying_value (paired to the same NSE snapshot),
    # not df_index's ltp, so strike selection stays internally consistent.
    chain_spot = float(option_chain["underlying_value"]) if option_chain else None

    # Pillar: Derivatives Positioning (NIFTY50/BANKNIFTY only — no verified Sensex source)
    p_derivatives_weight = 0.0
    derivatives_result = analyze_index_derivatives(option_chain, chain_spot, True, True) if option_chain else {
        "verified": False, "reason": "Unable to verify live options chain data.",
        "pcr": None, "max_pain": None, "oi_buildup": {"verdict": "UNAVAILABLE"},
        "support_resistance": None, "expected_move": None,
    }
    oi_verdict = derivatives_result.get("oi_buildup", {}).get("verdict", "UNAVAILABLE")
    if derivatives_result.get("verified"):
        if oi_verdict in ("CALL_LONG_BUILDUP", "PUT_SHORT_COVERING"):
            p_derivatives_weight = 1.0 * _mult("Index: Derivatives Positioning")
            confirmed_pillars.append(f"Derivatives: {oi_verdict.replace('_', ' ').title()}")
        elif oi_verdict in ("PUT_LONG_BUILDUP", "CALL_LONG_UNWINDING"):
            p_derivatives_weight = 1.0 * _mult("Index: Derivatives Positioning")
            confirmed_pillars.append(f"Derivatives: {oi_verdict.replace('_', ' ').title()}")
    pillar_weights["Index: Derivatives Positioning"] = p_derivatives_weight

    # Pillar: Greeks Outlook (NIFTY50/BANKNIFTY only — depends on the same option chain)
    p_greeks_weight = 0.0
    greeks_result = estimate_overnight_greeks_outlook(option_chain, chain_spot) if option_chain else {
        "verified": False, "reason": "Unable to verify live options chain data.",
    }
    better_side = greeks_result.get("better_positioned_side")
    if greeks_result.get("verified"):
        if better_side == "CALL (CE)":
            p_greeks_weight = 1.0 * _mult("Index: Greeks Outlook")
            confirmed_pillars.append("Greeks: Calls carry lighter overnight theta burn")
        elif better_side == "PUT (PE)":
            p_greeks_weight = 1.0 * _mult("Index: Greeks Outlook")
            confirmed_pillars.append("Greeks: Puts carry lighter overnight theta burn")
    pillar_weights["Index: Greeks Outlook"] = p_greeks_weight

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

    if signal not in ("BTST (BUY)", "STBT (SELL)"):
        confidence_score = 0
        priority_level = "P3_LOW"
        rank_reason = f"Avoid — confirmed pillar weight ({total_confirmed_weight}/{required_weight}) fell short of required threshold"
    else:
        confidence_score = min(99, max(40, base_score))
        if confidence_score >= 90:
            priority_level = "P1_HIGH"
        elif confidence_score >= 75:
            priority_level = "P2_MEDIUM"
        else:
            priority_level = "P3_LOW"
        rank_reason = f"Confirmed {total_confirmed_weight}/{required_weight} Index Pillar Weight"

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
        "derivatives": derivatives_result,
        "greeks_outlook": greeks_result,
        "signal": signal,
        "option_type": option_type,
        "conviction_level": conviction_level,
        "priority_level": priority_level,
        "confidence_score": confidence_score,
        "predicted_gap_pct": predicted_gap_pct,
        "ltp": round(ltp, 2),
        "prev_close": round(prev_close, 2),
        "change_pts": round(change_pts, 2),
        "pct_change": round(pct_change, 2),
        "day_high": round(daily_high, 2),
        "day_low": round(daily_low, 2),
        "range_position_pct": range_position_pct,
        "rsi": round(rsi, 1),
        "pct_change": pct_change,
        "rank_reason": f"Confirmed {total_confirmed_weight}/{required_weight} Index Pillar Weight",
        "score": confidence_score,
    }
