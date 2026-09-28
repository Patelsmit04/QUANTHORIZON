"""
SMART MONEY CONCEPTS (SMC) HELPER ENGINE — Library-Backed
==========================================================
Adapter layer that delegates institutional SMC pattern detection to
the battle-tested `smartmoneyconcepts` PyPI package while preserving
the exact same public API that smc_strategy.py / smc_scanner.py /
strategy_manager.py consume:

Public functions (signatures & return types unchanged):
  - find_swing_pivots(df, left, right) -> dict
  - detect_market_structure(df) -> Optional[str]
  - detect_liquidity_sweep(df) -> Optional[str]
  - find_nearest_order_block(df, direction) -> Optional[dict]
  - find_nearest_fvg(df, direction) -> Optional[dict]
  - premium_discount_zone(df) -> str
  - check_inducement_cleared(df) -> bool
  - next_opposing_liquidity_pool(df) -> float
  - distance_pct(entry, target) -> float

Replaces: 239-line hand-rolled detection engine (2026-09-18).
"""

import logging
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

try:
    from smartmoneyconcepts.smc import smc as _smc_lib
    _HAS_SMC_LIB = True
except ImportError:
    _HAS_SMC_LIB = False

logger = logging.getLogger("SMCHelpers")


# ---------------------------------------------------------------------------
# Internal: column normalization
# ---------------------------------------------------------------------------

def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with lowercase columns required by the library.
    
    The smartmoneyconcepts library expects columns:
        open, high, low, close, volume
    Our DataFrames use Title-Case: Open, High, Low, Close, Volume.
    """
    ohlc = df.copy()
    ohlc.columns = ohlc.columns.str.lower()
    # Ensure required columns exist
    for col in ("open", "high", "low", "close"):
        if col not in ohlc.columns:
            logger.warning("OHLC DataFrame missing '%s' column", col)
            return ohlc
    if "volume" not in ohlc.columns:
        ohlc["volume"] = 0
    return ohlc


# ---------------------------------------------------------------------------
# Utility functions (kept as-is — pure math, not in library)
# ---------------------------------------------------------------------------

def distance_pct(entry: float, target: float) -> float:
    """Calculates percentage distance between entry and target prices."""
    if entry is None or target is None or entry <= 0:
        return 1.5
    return round(abs(entry - target) / entry * 100, 2)


# ---------------------------------------------------------------------------
# 1. Swing Pivots — library-backed
# ---------------------------------------------------------------------------

def find_swing_pivots(df: pd.DataFrame, left: int = 2, right: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    """Finds fractal swing highs and swing lows across OHLC dataframe.
    
    Delegates to smc.swing_highs_lows() which returns a Series with values
    1 (swing high) and -1 (swing low) at the pivot indices.
    """
    if df is None or len(df) < 5:
        return {"swing_highs": [], "swing_lows": []}

    if not _HAS_SMC_LIB:
        return _find_swing_pivots_fallback(df, left, right)

    try:
        ohlc = _normalize_ohlc(df)
        swing_length = max(left, right, 2)
        swing_hl = _smc_lib.swing_highs_lows(ohlc, swing_length=swing_length)

        shs = []
        sls = []
        highs = df["High"].values
        lows = df["Low"].values

        for i in range(len(swing_hl)):
            val = swing_hl.iloc[i]
            if isinstance(val, (pd.Series, np.ndarray)):
                val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
            if val == 1:
                shs.append({"index": i, "price": float(highs[i])})
            elif val == -1:
                sls.append({"index": i, "price": float(lows[i])})

        if shs or sls:
            return {"swing_highs": shs, "swing_lows": sls}
        # Library returned nothing useful — fallback
        return _find_swing_pivots_fallback(df, left, right)
    except Exception as e:
        logger.debug("swing_highs_lows library call failed: %s — using fallback", e)
        return _find_swing_pivots_fallback(df, left, right)


def _find_swing_pivots_fallback(df: pd.DataFrame, left: int = 2, right: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    """Original fractal pivot detection — used as fallback."""
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


# ---------------------------------------------------------------------------
# 2. Market Structure (BOS / CHoCH) — library-backed
# ---------------------------------------------------------------------------

def detect_market_structure(df: pd.DataFrame) -> Optional[str]:
    """
    Identifies Market Structure Shifts via smc.bos_choch().
    Returns 'bullish_bos', 'bearish_bos', 'bullish_choch', 'bearish_choch', or None.
    """
    if df is None or len(df) < 10:
        return None

    if not _HAS_SMC_LIB:
        return _detect_market_structure_fallback(df)

    try:
        ohlc = _normalize_ohlc(df)
        swing_hl = _smc_lib.swing_highs_lows(ohlc, swing_length=5)
        bos_choch = _smc_lib.bos_choch(ohlc, swing_hl)

        # bos_choch returns a DataFrame with columns: BOS, CHOCH, Level, BrokenIndex
        # Values in BOS/CHOCH columns are 1 (bullish) or -1 (bearish) or 0/NaN (none)
        if bos_choch is None or bos_choch.empty:
            return _detect_market_structure_fallback(df)

        # Look at the most recent non-NaN signal
        for i in range(len(bos_choch) - 1, -1, -1):
            row = bos_choch.iloc[i]

            # Check CHOCH first (higher significance)
            choch_val = row.get("CHOCH", np.nan)
            if not pd.isna(choch_val) and choch_val != 0:
                return "bullish_choch" if choch_val == 1 else "bearish_choch"

            # Then check BOS
            bos_val = row.get("BOS", np.nan)
            if not pd.isna(bos_val) and bos_val != 0:
                return "bullish_bos" if bos_val == 1 else "bearish_bos"

        return _detect_market_structure_fallback(df)
    except Exception as e:
        logger.debug("bos_choch library call failed: %s — using fallback", e)
        return _detect_market_structure_fallback(df)


def _detect_market_structure_fallback(df: pd.DataFrame) -> Optional[str]:
    """Original structure detection — used as fallback."""
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


# ---------------------------------------------------------------------------
# 3. Liquidity Sweeps — library-backed
# ---------------------------------------------------------------------------

def detect_liquidity_sweep(df: pd.DataFrame) -> Optional[str]:
    """
    Detects Liquidity Sweeps via smc.liquidity().
    Returns 'buy_side_swept', 'sell_side_swept', or None.
    """
    if df is None or len(df) < 10:
        return None

    if not _HAS_SMC_LIB:
        return _detect_liquidity_sweep_fallback(df)

    try:
        ohlc = _normalize_ohlc(df)
        swing_hl = _smc_lib.swing_highs_lows(ohlc, swing_length=5)
        liq = _smc_lib.liquidity(ohlc, swing_hl)

        # liq returns a DataFrame with columns: Liquidity, Level, End, Swept
        # Liquidity values: 1 = buy-side liquidity, -1 = sell-side liquidity
        if liq is None or liq.empty:
            return _detect_liquidity_sweep_fallback(df)

        # Look at most recent swept liquidity
        for i in range(len(liq) - 1, -1, -1):
            row = liq.iloc[i]
            swept_val = row.get("Swept", np.nan)
            liq_val = row.get("Liquidity", np.nan)

            if not pd.isna(swept_val) and swept_val != 0 and not pd.isna(liq_val):
                # Buy-side liquidity swept → price went above buy-side pool then came back
                if liq_val == 1:
                    return "buy_side_swept"
                elif liq_val == -1:
                    return "sell_side_swept"

        return _detect_liquidity_sweep_fallback(df)
    except Exception as e:
        logger.debug("liquidity library call failed: %s — using fallback", e)
        return _detect_liquidity_sweep_fallback(df)


def _detect_liquidity_sweep_fallback(df: pd.DataFrame) -> Optional[str]:
    """Original liquidity sweep detection — used as fallback."""
    if df is None or len(df) < 10:
        return None

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values

    recent_high = max(highs[-5:-1])
    recent_low = min(lows[-5:-1])

    curr_high = highs[-1]
    curr_low = lows[-1]
    curr_close = closes[-1]

    if curr_low < recent_low and curr_close > recent_low:
        return "sell_side_swept"
    if curr_high > recent_high and curr_close < recent_high:
        return "buy_side_swept"

    return None


# ---------------------------------------------------------------------------
# 4. Order Blocks — library-backed
# ---------------------------------------------------------------------------

def find_nearest_order_block(df: pd.DataFrame, direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """Finds nearest Order Block (OB) zone level and invalidation price via smc.ob()."""
    if df is None or len(df) < 10 or not direction:
        return None

    if not _HAS_SMC_LIB:
        return _find_nearest_order_block_fallback(df, direction)

    try:
        ohlc = _normalize_ohlc(df)
        swing_hl = _smc_lib.swing_highs_lows(ohlc, swing_length=5)
        obs = _smc_lib.ob(ohlc, swing_hl)

        # obs returns DataFrame with columns: OB, Top, Bottom, OBVolume, MitigatedIndex, Percentage
        # OB values: 1 = bullish OB (demand), -1 = bearish OB (supply)
        if obs is None or obs.empty:
            return _find_nearest_order_block_fallback(df, direction)

        is_bullish = "bullish" in direction.lower()
        target_val = 1 if is_bullish else -1

        # Scan from most recent backward for matching OB
        for i in range(len(obs) - 1, -1, -1):
            row = obs.iloc[i]
            ob_val = row.get("OB", np.nan)

            if not pd.isna(ob_val) and ob_val == target_val:
                top = float(row.get("Top", 0))
                bottom = float(row.get("Bottom", 0))
                mitigated = row.get("MitigatedIndex", np.nan)

                # Skip already mitigated OBs
                if not pd.isna(mitigated) and mitigated > 0:
                    continue

                if is_bullish:
                    return {
                        "level": top,
                        "invalidation": round(bottom * 0.997, 2),
                        "top": top,
                        "bottom": bottom
                    }
                else:
                    return {
                        "level": bottom,
                        "invalidation": round(top * 1.003, 2),
                        "top": top,
                        "bottom": bottom
                    }

        return _find_nearest_order_block_fallback(df, direction)
    except Exception as e:
        logger.debug("ob library call failed: %s — using fallback", e)
        return _find_nearest_order_block_fallback(df, direction)


def _find_nearest_order_block_fallback(df: pd.DataFrame, direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """Original OB detection — used as fallback."""
    if df is None or len(df) < 10 or not direction:
        return None

    closes = df["Close"].values
    opens = df["Open"].values
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    if "bullish" in direction.lower():
        for i in range(n - 2, 1, -1):
            if closes[i] < opens[i] and closes[i + 1] > highs[i]:
                return {
                    "level": float(highs[i]),
                    "invalidation": float(lows[i] * 0.997),
                    "top": float(highs[i]),
                    "bottom": float(lows[i])
                }
    elif "bearish" in direction.lower():
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


# ---------------------------------------------------------------------------
# 5. Fair Value Gaps — library-backed
# ---------------------------------------------------------------------------

def find_nearest_fvg(df: pd.DataFrame, direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """Finds nearest Fair Value Gap (FVG) level and invalidation price via smc.fvg()."""
    if df is None or len(df) < 5 or not direction:
        return None

    if not _HAS_SMC_LIB:
        return _find_nearest_fvg_fallback(df, direction)

    try:
        ohlc = _normalize_ohlc(df)
        fvgs = _smc_lib.fvg(ohlc)

        # fvgs returns DataFrame with columns: FVG, Top, Bottom, MitigatedIndex
        # FVG values: 1 = bullish FVG, -1 = bearish FVG
        if fvgs is None or fvgs.empty:
            return _find_nearest_fvg_fallback(df, direction)

        is_bullish = "bullish" in direction.lower()
        target_val = 1 if is_bullish else -1

        # Scan from most recent backward for matching FVG
        for i in range(len(fvgs) - 1, -1, -1):
            row = fvgs.iloc[i]
            fvg_val = row.get("FVG", np.nan)

            if not pd.isna(fvg_val) and fvg_val == target_val:
                top = float(row.get("Top", 0))
                bottom = float(row.get("Bottom", 0))
                mitigated = row.get("MitigatedIndex", np.nan)

                # Skip already mitigated FVGs
                if not pd.isna(mitigated) and mitigated > 0:
                    continue

                if is_bullish:
                    return {
                        "level": bottom,  # Entry at bottom of bullish FVG
                        "invalidation": round(bottom * 0.997, 2),
                        "top": top,
                        "bottom": bottom
                    }
                else:
                    return {
                        "level": top,  # Entry at top of bearish FVG
                        "invalidation": round(top * 1.003, 2),
                        "top": top,
                        "bottom": bottom
                    }

        return _find_nearest_fvg_fallback(df, direction)
    except Exception as e:
        logger.debug("fvg library call failed: %s — using fallback", e)
        return _find_nearest_fvg_fallback(df, direction)


def _find_nearest_fvg_fallback(df: pd.DataFrame, direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """Original FVG detection — used as fallback."""
    if df is None or len(df) < 5 or not direction:
        return None

    highs = df["High"].values
    lows = df["Low"].values
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


# ---------------------------------------------------------------------------
# 6–8. Simple utilities (kept as-is — not in library)
# ---------------------------------------------------------------------------

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
