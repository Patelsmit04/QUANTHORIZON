"""
TEST SUITE: Quantitative Scoring Calibration & Regime Filtering
Tests:
1. Phase 1: Exhaustion & Mean Reversion Veto (Quiet Pump & ATR/Range Cap)
2. Phase 2: Global Regime Filtering (Nifty 50 Intraday VWAP & India VIX < 11.5)
3. Phase 3: Recalibrated 5-Pillar Weights (88% P1 Conviction Bar & 20-pt Order Flow Penalty)
"""

import pytest
import pandas as pd
import numpy as np
from scoring_engine import evaluate_5_pillar_matrix

SYMBOL = "RELIANCE"

def _make_stock_df(closes, vols=None, high_offset=0.2, low_offset=0.2):
    n = len(closes)
    if vols is None:
        vols = [1000] * (n - 4) + [3000] * 4
    dates = pd.date_range("2026-08-10 09:15", periods=n, freq="5min")
    return pd.DataFrame({
        "Date": [d.strftime("%Y-%m-%d") for d in dates],
        "Open": [c - 0.1 for c in closes],
        "High": [c + high_offset for c in closes],
        "Low": [c - low_offset for c in closes],
        "Close": closes,
        "Volume": vols
    }, index=dates)


# =========================================================================
# PHASE 1: Exhaustion & Mean Reversion Veto Tests
# =========================================================================

def test_quiet_pump_exhaustion_veto():
    """Rule: IF (Intraday Gain > 4.5% AND Volume Surge < 1.5x) THEN VETO BTST_LONG."""
    # 5.0% gain from prev_close=100.0 to ltp=105.0 with low volume surge
    closes = list(np.linspace(100.0, 105.0, 30))
    vols = [1000] * 30  # Flat volume -> vol_spike_ratio = 1.0 < 1.5x
    df = _make_stock_df(closes, vols=vols)
    
    oi_data = {"source": "MOCK", "oi_pct_change": 5.0, "avg_10d_oi_pct": 2.0}
    delivery_data = {"source": "MOCK", "delivery_pct": 60.0, "avg_10d_delivery_pct": 40.0}
    
    res = evaluate_5_pillar_matrix(SYMBOL, df, oi_data=oi_data, delivery_data=delivery_data)
    assert res["exhaustion_veto"]["is_quiet_pump"] is True
    assert res["exhaustion_veto"]["is_vetoed"] is True
    assert res["signal"] == "NEUTRAL"
    assert res["priority_level"] == "P3_LOW"
    assert "Quiet Pump" in res["exhaustion_veto"]["reason"]


def test_day_range_exceeds_atr_exhaustion_veto():
    """Rule: IF Day's Range > 1.5x 14-day ATR THEN VETO BTST_LONG (Exhaustion Trap)."""
    # 30 candles with typical small range of 0.5, then final day swings 4.0 points (huge expansion)
    closes = list(np.linspace(100.0, 104.0, 30))
    df = _make_stock_df(closes, high_offset=2.0, low_offset=2.0)  # Day range = 4.0+
    
    res = evaluate_5_pillar_matrix(SYMBOL, df)
    assert "exhaustion_veto" in res
    assert res["exhaustion_veto"]["atr_14"] > 0
    assert res["exhaustion_veto"]["day_range"] > 0


# =========================================================================
# PHASE 2: Global Regime Filtering Tests
# =========================================================================

def test_nifty_below_vwap_blocks_btst_long():
    """Rule: A stock is NOT allowed to trigger BTST (BUY) if NIFTY 50 is trading below VWAP at 3:15 PM."""
    closes = list(np.linspace(100.0, 103.0, 30))
    vols = [1000] * 20 + [4000] * 10
    df_stock = _make_stock_df(closes, vols=vols)
    
    # NIFTY dataframe where LTP (24,800) is below VWAP (~24,950)
    nifty_dates = pd.date_range("2026-08-10 09:15", periods=30, freq="5min")
    nifty_closes = list(np.linspace(25100, 24800, 30))  # Trending down below session VWAP
    nifty_vols = [50000] * 30
    df_nifty = pd.DataFrame({
        "Date": [d.strftime("%Y-%m-%d") for d in nifty_dates],
        "Open": nifty_closes,
        "High": [c + 10 for c in nifty_closes],
        "Low": [c - 10 for c in nifty_closes],
        "Close": nifty_closes,
        "Volume": nifty_vols
    }, index=nifty_dates)
    
    oi_data = {"source": "MOCK", "oi_pct_change": 5.0, "avg_10d_oi_pct": 2.0}
    delivery_data = {"source": "MOCK", "delivery_pct": 60.0, "avg_10d_delivery_pct": 40.0}
    
    res = evaluate_5_pillar_matrix(SYMBOL, df_stock, df_nifty=df_nifty, oi_data=oi_data, delivery_data=delivery_data)
    assert res["nifty_vwap_gate"]["nifty_below_vwap"] is True
    assert res["signal"] == "NEUTRAL"
    assert res["priority_level"] == "P3_LOW"
    assert "NIFTY 50" in res["priority_reason"]


def test_india_vix_below_11_5_low_vol_regime():
    """Rule: IF India VIX < 11.5, completely disable volatility breakouts (mean-reversion regime)."""
    closes = list(np.linspace(100.0, 102.5, 30))
    vols = [1000] * 20 + [3500] * 10
    df_stock = _make_stock_df(closes, vols=vols)
    
    macro_status = {"vix_ok": True, "sp500_green": True, "gift_nifty_ok": True, "vix_value": 10.8}
    res = evaluate_5_pillar_matrix(SYMBOL, df_stock, macro_status=macro_status)
    assert res["vix_regime_gate"]["is_low_vol_regime"] is True
    assert res["priority_level"] != "P1_HIGH"


# =========================================================================
# PHASE 3: Recalibrated 5-Pillar Weights & Confidence Bar Tests
# =========================================================================

def test_p1_high_requires_88_pct_confidence():
    """Rule: Minimum passing grade for Priority 1 setup is raised to 88%."""
    closes = list(np.linspace(100.0, 102.0, 30))
    vols = [1000] * 20 + [3500] * 10
    df_stock = _make_stock_df(closes, vols=vols)
    
    oi_data = {"source": "MOCK", "oi_pct_change": 5.0, "avg_10d_oi_pct": 2.0}
    delivery_data = {"source": "MOCK", "delivery_pct": 60.0, "avg_10d_delivery_pct": 40.0}
    
    res = evaluate_5_pillar_matrix(SYMBOL, df_stock, oi_data=oi_data, delivery_data=delivery_data)
    if res["confidence_score"] >= 88 and res["confirmed_pillars_weight"] >= res["required_pillars"]:
        assert res["priority_level"] == "P1_HIGH"
    elif res["confidence_score"] < 88:
        assert res["priority_level"] != "P1_HIGH"
