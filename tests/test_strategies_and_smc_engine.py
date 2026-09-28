import pytest
import pandas as pd
import numpy as np
from datetime import datetime, time
from fastapi.testclient import TestClient

from app import app
import smc_helpers
import smc_strategy
import strategy_engine_rules as rules

client = TestClient(app)

def create_synthetic_ohlcv(n=50, trend="bullish"):
    dates = pd.date_range("2026-08-19 09:15", periods=n, freq="5min")
    prices = np.linspace(100, 120 if trend == "bullish" else 80, n)
    highs = prices + 1.0
    lows = prices - 1.0
    opens = prices - 0.2
    closes = prices + 0.2
    volumes = np.random.randint(1000, 5000, n)
    df = pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes
    }, index=dates)
    return df

def test_smc_pivots_right_confirmation_no_repainting():
    df = create_synthetic_ohlcv(30)
    # Inject a known pivot high at index 15
    df.iloc[15, df.columns.get_loc("High")] = 200.0
    pivots = smc_helpers.find_swing_pivots(df, left=2, right=2)
    sh_indices = [p["index"] for p in pivots["swing_highs"]]
    # Pivot at 15 should be detected (library or fallback)
    assert 15 in sh_indices

def test_smc_pivots_return_format():
    """Verify pivot return format is {swing_highs: [{index, price}, ...], swing_lows: [...]}."""
    df = create_synthetic_ohlcv(40)
    pivots = smc_helpers.find_swing_pivots(df, left=2, right=2)
    assert isinstance(pivots, dict)
    assert "swing_highs" in pivots
    assert "swing_lows" in pivots
    for p in pivots["swing_highs"]:
        assert "index" in p
        assert "price" in p
    for p in pivots["swing_lows"]:
        assert "index" in p
        assert "price" in p

def test_smc_strategy_evaluation():
    df = create_synthetic_ohlcv(40, "bullish")
    res = smc_strategy.evaluate_smc_setup("RELIANCE", df)
    assert "strategy_id" in res
    assert res["strategy_id"] == "smc-institutional-v1"
    assert "signal" in res

def test_smc_market_structure_returns_valid():
    """detect_market_structure should return None or a valid structure string."""
    df = create_synthetic_ohlcv(50, "bullish")
    result = smc_helpers.detect_market_structure(df)
    valid = {None, "bullish_bos", "bearish_bos", "bullish_choch", "bearish_choch"}
    assert result in valid

def test_smc_liquidity_sweep_returns_valid():
    """detect_liquidity_sweep should return None or a valid sweep string."""
    df = create_synthetic_ohlcv(50)
    result = smc_helpers.detect_liquidity_sweep(df)
    valid = {None, "buy_side_swept", "sell_side_swept"}
    assert result in valid

def test_smc_order_block_returns_valid():
    """find_nearest_order_block should return None or dict with level/invalidation."""
    df = create_synthetic_ohlcv(50, "bullish")
    result = smc_helpers.find_nearest_order_block(df, direction="bullish_bos")
    if result is not None:
        assert "level" in result
        assert "invalidation" in result

def test_smc_fvg_returns_valid():
    """find_nearest_fvg should return None or dict with level/invalidation."""
    df = create_synthetic_ohlcv(50, "bullish")
    result = smc_helpers.find_nearest_fvg(df, direction="bullish_bos")
    if result is not None:
        assert "level" in result
        assert "invalidation" in result

def test_smc_premium_discount_zone():
    """premium_discount_zone should return one of premium/discount/equilibrium."""
    df = create_synthetic_ohlcv(30)
    result = smc_helpers.premium_discount_zone(df)
    assert result in {"premium", "discount", "equilibrium"}

def test_smc_distance_pct():
    """distance_pct utility should calculate correctly."""
    assert smc_helpers.distance_pct(100, 102) == 2.0
    assert smc_helpers.distance_pct(100, 98) == 2.0
    assert smc_helpers.distance_pct(0, 100) == 1.5  # edge case
    assert smc_helpers.distance_pct(None, 100) == 1.5

def test_smc_library_available():
    """Verify that the smartmoneyconcepts library is installed and importable."""
    assert smc_helpers._HAS_SMC_LIB is True, "smartmoneyconcepts library not installed"

def test_strategy_a_vwap_pullback():
    df = create_synthetic_ohlcv(30, "bullish")
    # Evaluate pure function
    res = rules.evaluate_vwap_pullback(df)
    # Should safely return None or dict, never error
    assert res is None or isinstance(res, dict)

def test_strategy_c_orb_isolation():
    df = create_synthetic_ohlcv(50)
    session_date = df.index[0].date()
    levels = rules.compute_orb_levels(df, session_date)
    assert levels is not None
    assert "orb_high" in levels
    assert "orb_low" in levels
    assert levels["orb_high"] >= levels["orb_low"]

def test_strategy_f_volatility_straddle():
    # True only when both lower IV percentile and 48h event exist
    assert rules.evaluate_volatility_straddle(False, True) is None
    assert rules.evaluate_volatility_straddle(True, False) is None
    res = rules.evaluate_volatility_straddle(True, True)
    assert res is not None
    assert res["strategy_key"] == "volatility_straddle"
    assert res["option_type"] == "BOTH"

def test_strategies_api_endpoints():
    # 1. GET /api/strategies
    res = client.get("/api/strategies")
    assert res.status_code == 200
    assert "strategies" in res.json()

    # 2. POST /api/strategies/clarify
    clarify_res = client.post("/api/strategies/clarify", json={"strategy_text": "Buy Nifty 50 call when 5m RSI > 60 and price crosses VWAP"})
    assert clarify_res.status_code == 200
    data = clarify_res.json()
    assert "timeframe" in data
    assert "indicators" in data

    # 3. GET & POST /api/strategies/smc/backtest
    bt_res = client.get("/api/strategies/smc/backtest")
    assert bt_res.status_code == 200
    assert "is_validated" in bt_res.json()

    bt_post = client.post("/api/strategies/smc/backtest")
    assert bt_post.status_code == 200
    assert "is_validated" in bt_post.json()
