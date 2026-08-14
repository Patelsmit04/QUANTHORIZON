"""
STATELESS SMART MONEY CONCEPTS (SMC) HELPER ENGINE
===================================================
Pure, stateless helper functions for institutional SMC pattern analysis:
- Market Structure Shifts (BOS / CHoCH)
- Liquidity Sweeps (EQH / EQL stop hunts)
- Order Blocks (OB) & Fair Value Gaps (FVG)
- Premium / Discount / Equilibrium Zones
- Inducement Clearance & Opposing Liquidity Targets
"""

import logging
from typing import Dict, List, Any, Optional
import pandas as pd

logger = logging.getLogger("SMCHelpers")


def distance_pct(entry: float, target: float) -> float:
    """Calculates percentage distance between entry and target prices."""
    if entry is None or target is None or entry <= 0:
        return 1.5
    return round(abs(entry - target) / entry * 100, 2)


def find_swing_pivots(df: pd.DataFrame, left: int = 2, right: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    """Finds fractal swing highs and swing lows across OHLC dataframe."""
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)
    shs = []
    sls = []

    for i in range(left, n - right):
        is_sh = all(highs[i] >= highs[i - j] for j in range(1, left + 1)) and \
                all(highs[i] >= highs[i + j] for j in range(1, right + 1))
        if is_sh:
            shs.append({"index": i, "price": float(highs[i])})

        is_sl = all(lows[i] <= lows[i - j] for j in range(1, left + 1)) and \
                all(lows[i] <= lows[i + j] for j in range(1, right + 1))
        if is_sl:
            sls.append({"index": i, "price": float(lows[i])})

    return {"swing_highs": shs, "swing_lows": sls}


def detect_market_structure(df: pd.DataFrame) -> Optional[str]:
    """
    Identifies Market Structure Shifts:
    Returns 'bullish_bos', 'bearish_bos', 'bullish_choch', 'bearish_choch', or None.
    """
    if df is None or len(df) < 10:
        return None

    pivots = find_swing_pivots(df)
    shs = pivots["swing_highs"]
    sls = pivots["swing_lows"]

    if len(shs) < 2 or len(sls) < 2:
        return None

    close = float(df["Close"].iloc[-1])
    recent_sh = shs[-1]["price"]
    prev_sh = shs[-2]["price"]
    recent_sl = sls[-1]["price"]
    prev_sl = sls[-2]["price"]

    is_uptrend = recent_sh > prev_sh and recent_sl > prev_sl
    is_downtrend = recent_sh < prev_sh and recent_sl < prev_sl

    if close > recent_sh:
        return "bullish_bos" if is_uptrend else "bullish_choch"
    elif close < recent_sl:
        return "bearish_bos" if is_downtrend else "bearish_choch"

    return None


def detect_liquidity_sweep(df: pd.DataFrame) -> Optional[str]:
    """
    Detects Liquidity Sweeps (spikes past equal highs/lows followed by reversal):
    Returns 'buy_side_swept', 'sell_side_swept', or None.
    """
    if df is None or len(df) < 10:
        return None

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    opens = df["Open"].values

    recent_high = max(highs[-5:-1])
    recent_low = min(lows[-5:-1])

    curr_high = highs[-1]
    curr_low = lows[-1]
    curr_close = closes[-1]

    # Sell-Side Liquidity Swept: Wick pierces low, but body closes back inside
    if curr_low < recent_low and curr_close > recent_low:
        return "sell_side_swept"

    # Buy-Side Liquidity Swept: Wick pierces high, but body closes back inside
    if curr_high > recent_high and curr_close < recent_high:
        return "buy_side_swept"

    return None


def find_nearest_order_block(df: pd.DataFrame, direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """Finds nearest Order Block (OB) zone level and invalidation price."""
    if df is None or len(df) < 10 or not direction:
        return None

    closes = df["Close"].values
    opens = df["Open"].values
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    if "bullish" in direction.lower():
        # Last down candle before strong up move
        for i in range(n - 2, 1, -1):
            if closes[i] < opens[i] and closes[i + 1] > highs[i]:
                return {
                    "level": float(highs[i]),
                    "invalidation": float(lows[i] * 0.997),
                    "top": float(highs[i]),
                    "bottom": float(lows[i])
                }
    elif "bearish" in direction.lower():
        # Last up candle before strong down move
        for i in range(n - 2, 1, -1):
            if closes[i] > opens[i] and closes[i + 1] < lows[i]:
                return {
                    "level": float(lows[i]),
                    "invalidation": float(highs[i] * 1.003),
                    "top": float(highs[i]),
                    "bottom": float(lows[i])
                }

    latest_close = float(closes[-1])
    return {
        "level": latest_close,
        "invalidation": round(latest_close * (0.993 if "bullish" in direction.lower() else 1.007), 2)
    }


def find_nearest_fvg(df: pd.DataFrame, direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """Finds nearest Fair Value Gap (FVG) level and invalidation price."""
    if df is None or len(df) < 5 or not direction:
        return None

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    n = len(df)

    if "bullish" in direction.lower():
        for i in range(n - 1, 2, -1):
            if lows[i] > highs[i - 2]:
                return {
                    "level": float(lows[i]),
                    "invalidation": float(highs[i - 2] * 0.997),
                    "top": float(lows[i]),
                    "bottom": float(highs[i - 2])
                }
    elif "bearish" in direction.lower():
        for i in range(n - 1, 2, -1):
            if highs[i] < lows[i - 2]:
                return {
                    "level": float(highs[i]),
                    "invalidation": float(lows[i - 2] * 1.003),
                    "top": float(lows[i - 2]),
                    "bottom": float(highs[i])
                }

    return None


def premium_discount_zone(df: pd.DataFrame) -> str:
    """
    Calculates Fibonacci range position across current structure leg:
    Returns 'premium' (>50%), 'discount' (<50%), or 'equilibrium' (45-55%).
    """
    if df is None or len(df) < 5:
        return "equilibrium"

    highs = df["High"].values
    lows = df["Low"].values
    close = float(df["Close"].iloc[-1])

    max_h = max(highs[-20:])
    min_l = min(lows[-20:])
    rng = max_h - min_l

    if rng <= 0:
        return "equilibrium"

    pos = (close - min_l) / rng
    if 0.45 <= pos <= 0.55:
        return "equilibrium"
    elif pos < 0.45:
        return "discount"
    else:
        return "premium"


def check_inducement_cleared(df: pd.DataFrame) -> bool:
    """Filters out setups still trapped inside minor liquidity grabs."""
    if df is None or len(df) < 8:
        return True

    lows = df["Low"].values
    highs = df["High"].values
    close = float(df["Close"].iloc[-1])

    # Inducement is cleared if price has moved beyond minor 3-bar swing Extremes
    minor_high = max(highs[-4:-1])
    minor_low = min(lows[-4:-1])

    return (close > minor_high) or (close < minor_low) or (abs(close - minor_low) > abs(minor_high - minor_low) * 0.3)


def next_opposing_liquidity_pool(df: pd.DataFrame) -> float:
    """Locates next opposing liquidity pool (EQH/EQL or FVG level) for TP target."""
    if df is None or len(df) < 5:
        return float(df["Close"].iloc[-1] * 1.02) if df is not None else 100.0

    highs = df["High"].values
    lows = df["Low"].values
    close = float(df["Close"].iloc[-1])

    max_h = max(highs[-15:])
    min_l = min(lows[-15:])

    return max_h if close < max_h else float(close * 1.02)
