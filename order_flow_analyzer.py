"""
ORDER FLOW ANALYZER — 3:15-3:25 PM CLOSING AGGRESSION VETO ENGINE
===================================================================
Evaluates intraday order flow quality for candidate BTST/STBT setups in the 3:15-3:25 PM closing window.
Detects:
1. "Marking the Close" — concentrated single-print manipulation.
2. Directional bar agreement (requires >=7 of 10 1-minute bars).
3. 5-Level Depth Imbalance corroboration.
4. Data Gap Protection — never confirms or vetoes on a dropped WebSocket tick feed.
"""

import logging
from typing import Dict, Any
from zerodha_order_flow_provider import OrderFlowData

logger = logging.getLogger("OrderFlowAnalyzer")

MIN_DIRECTIONAL_BARS = 7          # Requires >=7 of 10 1-min bars to agree in direction
MIN_AVG_TICK_BREADTH = 100        # Minimum average ticks/min to confirm broad participation
MIN_DEPTH_IMBALANCE_RATIO = 1.15  # 5-level bid/ask depth imbalance corroboration ratio
EXPIRY_DAY_MULTIPLIER = 1.2       # Wider threshold on F&O expiry days


def check_closing_aggression(
    symbol: str,
    order_flow_data: OrderFlowData,
    signal_type: str = "BTST (BUY)",
    day_cvd_trend: str = "BULLISH",
    is_expiry_day: bool = False
) -> Dict[str, Any]:
    """
    Evaluates 3:15-3:25 PM order flow aggression.
    Returns structured dict with verdict:
    - 'confirmed': Strong sustained directional order flow + depth corroboration.
    - 'confirmed_against_trend': Strong late order flow reversing earlier intraday trend.
    - 'vetoed': Order flow fails bar consistency, depth imbalance, or breadth check.
    - 'insufficient_data': Data gap occurred or minute bars incomplete.
    """
    if not order_flow_data or order_flow_data.had_data_gap:
        return {
            "verdict": "insufficient_data",
            "reason": "Data gap detected during 3:15-3:25 PM window (>15s tick dropout) — order flow neutral.",
            "directional_bars_count": 0,
            "depth_confirms": False,
            "breadth_ok": False,
            "confirms_day_trend": False
        }

    bars = order_flow_data.minute_bars
    if len(bars) < 5:
        return {
            "verdict": "insufficient_data",
            "reason": f"Insufficient minute bars ({len(bars)}/10) available for evaluation.",
            "directional_bars_count": 0,
            "depth_confirms": False,
            "breadth_ok": False,
            "confirms_day_trend": False
        }

    is_bullish = "BTST" in signal_type or "BUY" in signal_type

    # 1. Count Directional Bar Agreement
    if is_bullish:
        directional_bars = sum(1 for b in bars if b.get("net_delta", 0) > 0)
    else:
        directional_bars = sum(1 for b in bars if b.get("net_delta", 0) < 0)

    # 2. Participation Breadth Check (proxy for distinct executions)
    total_ticks = sum(b.get("tick_count", 0) for b in bars)
    avg_ticks = total_ticks / len(bars)
    breadth_ok = avg_ticks >= MIN_AVG_TICK_BREADTH

    # 3. 5-Level Depth Imbalance Corroboration
    depth_info = order_flow_data.depth_imbalance
    depth_ratio = depth_info.get("depth_ratio", 1.0)
    if is_bullish:
        depth_confirms = depth_ratio >= MIN_DEPTH_IMBALANCE_RATIO
    else:
        depth_confirms = depth_ratio <= (1.0 / MIN_DEPTH_IMBALANCE_RATIO)

    # 4. Session CVD Trend Alignment
    confirms_day_trend = (is_bullish and day_cvd_trend == "BULLISH") or ((not is_bullish) and day_cvd_trend == "BEARISH")

    required_bars = int(MIN_DIRECTIONAL_BARS * EXPIRY_DAY_MULTIPLIER) if is_expiry_day else MIN_DIRECTIONAL_BARS

    # 5. Final Veto Classification Logic
    if directional_bars >= required_bars and breadth_ok and depth_confirms:
        verdict = "confirmed" if confirms_day_trend else "confirmed_against_trend"
        reason = f"Confirmed Order Flow: {directional_bars}/10 directional bars, 5L depth ratio {depth_ratio}x ({depth_info.get('bid_pct')}% bids)"
    elif directional_bars < 5 or not breadth_ok:
        verdict = "vetoed"
        reasons = []
        if directional_bars < 5:
            reasons.append(f"Only {directional_bars}/10 bars agree with {signal_type}")
        if not breadth_ok:
            reasons.append(f"Low participation tick count ({int(avg_ticks)} ticks/min < {MIN_AVG_TICK_BREADTH}) — possible marking-the-close")
        if not depth_confirms:
            reasons.append(f"Depth imbalance mismatch ({depth_ratio}x ratio)")
        reason = f"Order Flow VETOED: {'; '.join(reasons)}"
    else:
        verdict = "vetoed"
        reason = f"Order Flow VETOED: Moderate bar agreement ({directional_bars}/10) failed depth/breadth corroboration."

    return {
        "verdict": verdict,
        "reason": reason,
        "directional_bars_count": directional_bars,
        "total_bars": len(bars),
        "depth_confirms": depth_confirms,
        "depth_ratio": depth_ratio,
        "bid_pct": depth_info.get("bid_pct", 50.0),
        "ask_pct": depth_info.get("ask_pct", 50.0),
        "breadth_ok": breadth_ok,
        "avg_ticks_per_min": int(avg_ticks),
        "confirms_day_trend": confirms_day_trend
    }
