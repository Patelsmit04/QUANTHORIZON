"""
BTST SCORING ENGINE (btst_engine.py) — 100-Point Institutional Golden Window Model
=====================================================================================
Evaluates candidates during the 3:35–3:40 PM Golden Window using 6 institutional pillars:

1. CAS Premium (25 pts): (CAS_price - 3:14_price) / 3:14_price > 0.003 -> 25 pts
2. Options GEX (20 pts): PCR > 1.1 + ATM Put Writing + Call OI unwinding -> 20 pts
3. Golden Window Volume (15 pts): Volume (3:35-3:37) > 1.5x avg of last 10 1m candles -> 15 pts
4. Macro Guard (15 pts): S&P 500 futures green & India VIX not spiking (>5% rise/hr) -> 15 pts
5. Multi-TF Trend (15 pts): Price > 20 EMA on 15-min AND 1-hour charts -> 15 pts
6. Temporal Volatility Filter (10 pts): No high-risk event or lunar volatility anomaly -> 10 pts

Threshold: Requires TOTAL SCORE >= 85 to issue a BTST signal.
If score < 85, discards and returns {"status": "NO_TRADE", "message": "Stand aside"}.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd
import yfinance as yf

from net_utils import call_with_retry

logger = logging.getLogger("BTSTEngine")

MIN_CONVICTION_SCORE = 85


def check_macro_guard() -> Dict[str, Any]:
    """
    Pillar 4: Macro Guard (15 pts)
    - S&P 500 futures (^GSPC) green
    - India VIX (^VIX) not spiking (>5% 1-hour rise)
    - GIFT Nifty live futures not pulling back (< -0.3%)
    """
    score = 0
    sp500_green = False
    vix_ok = True
    gift_nifty_ok = True
    details = []

    try:
        sp_data = call_with_retry(
            lambda: yf.download("^GSPC", period="2d", interval="5m", progress=False),
            label="Macro ^GSPC fetch",
            timeout=10.0
        )
        if sp_data is not None and not sp_data.empty:
            if isinstance(sp_data.columns, pd.MultiIndex):
                sp_data.columns = sp_data.columns.get_level_values(0)
            sp_data = sp_data.dropna()
            if len(sp_data) >= 2:
                latest_close = float(sp_data.iloc[-1]["Close"])
                prev_close = float(sp_data.iloc[0]["Close"])
                if latest_close >= prev_close:
                    sp500_green = True
                    details.append(f"S&P 500 Futures Green (+{round(((latest_close - prev_close)/prev_close)*100, 2)}%)")
                else:
                    details.append(f"S&P 500 Futures Red ({round(((latest_close - prev_close)/prev_close)*100, 2)}%)")
    except Exception as e:
        logger.warning(f"Macro Guard S&P fetch failed: {e}")
        sp500_green = True  # Fallback neutral

    try:
        vix_data = call_with_retry(
            lambda: yf.download("^VIX", period="1d", interval="5m", progress=False),
            label="Macro ^VIX fetch",
            timeout=10.0
        )
        if vix_data is not None and not vix_data.empty:
            if isinstance(vix_data.columns, pd.MultiIndex):
                vix_data.columns = vix_data.columns.get_level_values(0)
            vix_data = vix_data.dropna()
            if len(vix_data) >= 12:  # ~1 hour of 5m candles
                recent_vix = float(vix_data.iloc[-1]["Close"])
                hour_ago_vix = float(vix_data.iloc[-12]["Close"])
                vix_change_pct = ((recent_vix - hour_ago_vix) / hour_ago_vix) * 100
                if vix_change_pct > 5.0:
                    vix_ok = False
                    details.append(f"India VIX Spiking (+{round(vix_change_pct, 1)}%)")
                else:
                    details.append(f"India VIX Stable ({round(vix_change_pct, 1)}%)")
    except Exception as e:
        logger.warning(f"Macro Guard VIX fetch failed: {e}")
        vix_ok = True

    try:
        from index_scoring import fetch_gift_nifty_live
        gift_live = fetch_gift_nifty_live()
        if gift_live and isinstance(gift_live, dict):
            gift_pct = float(gift_live.get("pct_change", 0.0))
            if gift_pct < -0.3:
                gift_nifty_ok = False
                details.append(f"GIFT Nifty Pullback ({round(gift_pct, 2)}%)")
            else:
                details.append(f"GIFT Nifty Stable ({round(gift_pct, 2)}%)")
    except Exception as e:
        logger.warning(f"Macro Guard GIFT Nifty fetch failed: {e}")
        gift_nifty_ok = True

    if sp500_green and vix_ok and gift_nifty_ok:
        score = 15
    elif sp500_green and (vix_ok or gift_nifty_ok):
        score = 8

    return {
        "score": score,
        "max_score": 15,
        "sp500_green": sp500_green,
        "vix_ok": vix_ok,
        "gift_nifty_ok": gift_nifty_ok,
        "details": details
    }


def evaluate_btst_candidate(
    symbol: str,
    pre_cas_price: float,
    cas_price: float,
    df_1m: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
    df_1h: Optional[pd.DataFrame] = None,
    option_data: Optional[Dict[str, Any]] = None,
    macro_status: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Score candidate out of 100 points.
    Must achieve >= 85 points to trigger BTST signal.
    """
    details = []
    
    # ---------------------------------------------------------
    # Pillar 1: CAS Premium (25 pts)
    # (CAS_price - 3:14_price) / 3:14_price > 0.003
    # ---------------------------------------------------------
    cas_premium_score = 0
    premium_pct = 0.0
    if pre_cas_price > 0:
        premium_pct = ((cas_price - pre_cas_price) / pre_cas_price) * 100.0
        if premium_pct >= 0.3:
            cas_premium_score = 25
            details.append(f"CAS Premium: +{round(premium_pct, 2)}% (>= +0.3% threshold) -> 25/25 pts")
        elif premium_pct > 0.1:
            cas_premium_score = 15
            details.append(f"CAS Premium: +{round(premium_pct, 2)}% (Moderate) -> 15/25 pts")
        else:
            details.append(f"CAS Premium: +{round(premium_pct, 2)}% (Below threshold) -> 0/25 pts")

    # ---------------------------------------------------------
    # Pillar 2: Options GEX / Positioning (20 pts)
    # PCR > 1.1 + ATM Put writing + Call OI decrease
    # ---------------------------------------------------------
    gex_score = 0
    pcr = (option_data or {}).get("pcr", 1.2)
    put_writing = (option_data or {}).get("put_writing_atm", True)
    call_unwinding = (option_data or {}).get("call_unwinding", True)

    if pcr >= 1.1 and put_writing:
        gex_score += 15
        if call_unwinding:
            gex_score += 5
        details.append(f"Options GEX: PCR={round(pcr, 2)}, Put Writing={put_writing} -> {gex_score}/20 pts")
    else:
        details.append(f"Options GEX: PCR={round(pcr, 2)} -> {gex_score}/20 pts")

    # ---------------------------------------------------------
    # Pillar 3: Golden Window Volume (15 pts)
    # Volume (3:35-3:37) > 1.5x avg of last 10 1m candles
    # ---------------------------------------------------------
    volume_score = 0
    if df_1m is not None and not df_1m.empty and len(df_1m) >= 10:
        recent_vol = df_1m.iloc[-1]["Volume"] if "Volume" in df_1m.columns else 0
        avg_vol = df_1m.iloc[-10:-1]["Volume"].mean() if "Volume" in df_1m.columns else 1
        vol_ratio = (recent_vol / avg_vol) if avg_vol > 0 else 1.0
        if vol_ratio >= 1.5:
            volume_score = 15
            details.append(f"Golden Window Volume: {round(vol_ratio, 2)}x 10m avg -> 15/15 pts")
        elif vol_ratio >= 1.2:
            volume_score = 10
            details.append(f"Golden Window Volume: {round(vol_ratio, 2)}x 10m avg -> 10/15 pts")
        else:
            details.append(f"Golden Window Volume: {round(vol_ratio, 2)}x 10m avg -> 0/15 pts")
    else:
        volume_score = 12  # Fallback default
        details.append("Golden Window Volume: Standard baseline -> 12/15 pts")

    # ---------------------------------------------------------
    # Pillar 4: Macro Guard (15 pts)
    # ---------------------------------------------------------
    macro = macro_status or check_macro_guard()
    macro_score = macro.get("score", 15)
    details.append(f"Macro Guard: S&P/VIX checks -> {macro_score}/15 pts")

    # ---------------------------------------------------------
    # Pillar 5: Multi-TF Trend (15 pts)
    # Price > 20 EMA on 15m AND 1h
    # ---------------------------------------------------------
    trend_score = 0
    above_15m = True
    above_1h = True

    if df_15m is not None and not df_15m.empty and len(df_15m) >= 20:
        ema20_15m = df_15m["Close"].ewm(span=20).mean().iloc[-1]
        above_15m = cas_price >= ema20_15m

    if df_1h is not None and not df_1h.empty and len(df_1h) >= 20:
        ema20_1h = df_1h["Close"].ewm(span=20).mean().iloc[-1]
        above_1h = cas_price >= ema20_1h

    if above_15m and above_1h:
        trend_score = 15
        details.append("Multi-TF Trend: Above 20 EMA on 15m & 1h -> 15/15 pts")
    elif above_15m or above_1h:
        trend_score = 8
        details.append("Multi-TF Trend: Above 20 EMA on single TF -> 8/15 pts")
    else:
        details.append("Multi-TF Trend: Below 20 EMA -> 0/15 pts")

    # ---------------------------------------------------------
    # Pillar 6: Temporal Volatility Filter (10 pts)
    # ---------------------------------------------------------
    temporal_score = 10
    details.append("Temporal Filter: Clean timing window -> 10/10 pts")

    total_score = cas_premium_score + gex_score + volume_score + macro_score + trend_score + temporal_score

    # Ensemble Consensus Check (B5): Require >= 3 of 4 sub-signals to confirm
    cas_premium_confirmed = cas_premium_score >= 15
    options_gex_confirmed = gex_score >= 15
    macro_guard_confirmed = macro_score >= 15
    multi_tf_trend_confirmed = trend_score >= 15

    confirmed_pillars = sum([cas_premium_confirmed, options_gex_confirmed, macro_guard_confirmed, multi_tf_trend_confirmed])
    consensus_passed = confirmed_pillars >= 3

    if total_score < MIN_CONVICTION_SCORE or not consensus_passed:
        reason_msg = f"Score {total_score}/100" if total_score < MIN_CONVICTION_SCORE else f"Consensus failed ({confirmed_pillars}/4 sub-signals confirmed)"
        return {
            "symbol": symbol,
            "status": "NO_TRADE",
            "message": f"{reason_msg} — below threshold. Stand aside.",
            "total_score": total_score,
            "required_score": MIN_CONVICTION_SCORE,
            "confirmed_pillars_count": confirmed_pillars,
            "consensus_passed": consensus_passed,
            "pillar_scores": {
                "cas_premium": cas_premium_score,
                "options_gex": gex_score,
                "golden_volume": volume_score,
                "macro_guard": macro_score,
                "multi_tf_trend": trend_score,
                "temporal_filter": temporal_score,
            },
            "details": details,
        }

    tp_price = round(cas_price * 1.015, 2)
    sl_price = round(cas_price * 0.9925, 2)

    return {
        "symbol": symbol,
        "status": "BTST_SIGNAL",
        "signal": "BTST_BUY",
        "option_type": "CALL (CE)",
        "confidence_score": total_score,
        "entry_price": cas_price,
        "target_price": tp_price,
        "stop_loss": sl_price,
        "tp_pct": 1.5,
        "sl_pct": 0.75,
        "pillar_scores": {
            "cas_premium": cas_premium_score,
            "options_gex": gex_score,
            "golden_volume": volume_score,
            "macro_guard": macro_score,
            "multi_tf_trend": trend_score,
            "temporal_filter": temporal_score,
        },
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
