"""
SMART MONEY CONCEPTS (SMC) STRATEGY MODULE
===========================================
Integrates pure smc_helpers.py functions into the python_code evaluate_signal contract:
Structure Shifts (BOS/CHoCH) + Liquidity Sweeps + OB/FVG + Premium/Discount.
"""

import logging
from typing import Dict, Any, Optional
import pandas as pd
from smc_helpers import (
    detect_market_structure,
    detect_liquidity_sweep,
    find_nearest_order_block,
    find_nearest_fvg,
    premium_discount_zone,
    check_inducement_cleared,
    next_opposing_liquidity_pool,
    distance_pct
)

logger = logging.getLogger("SMCStrategy")
SMC_STRATEGY_ID = "smc-institutional-v1"


def evaluate_signal(df: pd.DataFrame, pillars_matrix: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """
    df: OHLCV dataframe, most recent bar last
    pillars_matrix: existing pillar scores dict, reused so SMC can still be
                     gated/combined with the standard confirmation pillars
                     if desired (set combine_with_pillars=False below to run pure SMC)
    """
    if df is None or df.empty or len(df) < 10:
        return None

    combine_with_pillars = False  # set True to require pillar score >= threshold too

    structure = detect_market_structure(df)          # returns 'bullish_bos','bearish_bos','bullish_choch','bearish_choch', or None
    swept = detect_liquidity_sweep(df)                # returns 'buy_side_swept','sell_side_swept', or None
    ob_zone = find_nearest_order_block(df, direction=structure)
    fvg_zone = find_nearest_fvg(df, direction=structure)
    zone_state = premium_discount_zone(df)            # returns 'premium','discount','equilibrium'
    inducement_clear = check_inducement_cleared(df)   # filters out setups still inside a minor liquidity grab

    signal = None
    entry = tp_pct = sl_pct = None

    # Bullish setup: CHoCH/BOS up + sell-side liquidity just swept + price in discount + at OB/FVG
    if structure in ('bullish_bos', 'bullish_choch') and (swept == 'sell_side_swept' or not swept) \
       and zone_state == 'discount' and inducement_clear and (ob_zone or fvg_zone):
        entry_zone = ob_zone or fvg_zone
        signal = 'BTST_BUY'
        entry = entry_zone['level']
        sl_pct = distance_pct(entry, entry_zone['invalidation'])       # just beyond OB/sweep low
        tp_pct = distance_pct(entry, next_opposing_liquidity_pool(df)) # next equal-high pool or FVG

    # Bearish setup: CHoCH/BOS down + buy-side liquidity just swept + price in premium + at OB/FVG
    elif structure in ('bearish_bos', 'bearish_choch') and (swept == 'buy_side_swept' or not swept) \
         and zone_state == 'premium' and inducement_clear and (ob_zone or fvg_zone):
        entry_zone = ob_zone or fvg_zone
        signal = 'STBT_SELL'
        entry = entry_zone['level']
        sl_pct = distance_pct(entry, entry_zone['invalidation'])
        tp_pct = distance_pct(entry, next_opposing_liquidity_pool(df))

    if signal is None:
        return None  # no setup — do not force a trade

    if combine_with_pillars and pillars_matrix:
        score = sum(pillars_matrix.values())
        if score < 3.0:
            return None  # SMC setup present but standard pillars disagree — skip

    return {
        'signal': signal,
        'entry': entry,
        'tp_pct': tp_pct,
        'sl_pct': sl_pct,
        'reason': f'{structure} + {swept} + {zone_state} zone, OB/FVG confirmed'
    }


def evaluate_smc_setup(symbol: str, df_stock: pd.DataFrame) -> Dict[str, Any]:
    """Compatibility wrapper around evaluate_signal for scanner pipeline."""
    res = evaluate_signal(df_stock)
    latest_close = float(df_stock["Close"].iloc[-1]) if df_stock is not None and not df_stock.empty else 0.0
    if not res:
        return {
            "symbol": symbol,
            "strategy_id": SMC_STRATEGY_ID,
            "strategy_name": "Smart Money Concepts (SMC)",
            "signal": "NEUTRAL",
            "confidence_score": 50,
            "entry_price": round(latest_close, 2),
            "tp_price": 0.0,
            "sl_price": 0.0,
            "reason": "No SMC setup detected"
        }

    sig = res["signal"]
    tp_pct = res.get("tp_pct", 1.5)
    sl_pct = res.get("sl_pct", 0.75)
    entry = res.get("entry", latest_close)

    tp_price = round(entry * (1 + tp_pct / 100) if "BUY" in sig else entry * (1 - tp_pct / 100), 2)
    sl_price = round(entry * (1 - sl_pct / 100) if "BUY" in sig else entry * (1 + sl_pct / 100), 2)

    return {
        "symbol": symbol,
        "strategy_id": SMC_STRATEGY_ID,
        "strategy_name": "Smart Money Concepts (SMC)",
        "signal": "BTST (BUY)" if "BUY" in sig else "STBT (SELL)",
        "confidence_score": 85,
        "entry_price": round(entry, 2),
        "tp_price": tp_price,
        "sl_price": sl_price,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "reason": res.get("reason", "SMC structure shift confirmed")
    }
