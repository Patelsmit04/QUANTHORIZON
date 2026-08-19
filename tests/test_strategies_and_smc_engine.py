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
    assert 15 in sh_indices
    # Pivot at 15 is only detected because n=30 > 15 + right (no lookahead beyond dataframe)

def test_smc_strategy_evaluation():
    df = create_synthetic_ohlcv(40, "bullish")
    res = smc_strategy.evaluate_smc_setup("RELIANCE", df)
    assert "strategy_id" in res
    assert res["strategy_id"] == "smc-institutional-v1"
    assert "signal" in res

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
