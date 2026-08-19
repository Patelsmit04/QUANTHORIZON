import os
import pytest
from fastapi.testclient import TestClient
from app import app, TRADEXO_API_KEY

client = TestClient(app)
auth_headers = {"X-API-Key": TRADEXO_API_KEY or "test"}

def test_api_scan_endpoint_returns_required_fields():
    from app import cache_store
    cache_store["scan_summary"] = {
        "stocks": [{"symbol": "RELIANCE", "priority_level": "P1_HIGH", "signal": "BTST (BUY)"}],
        "total_scanned": 210,
        "priority_1_count": 1,
        "btst_count": 1,
        "stbt_count": 0
    }
    res = client.get("/api/scan")
    assert res.status_code == 200
    data = res.json()
    assert "stocks" in data
    assert "total_scanned" in data
    assert "priority_1_count" in data
    assert "btst_count" in data
    assert "stbt_count" in data

def test_api_live_prices_endpoint_returns_required_fields():
    from app import cache_store
    cache_store["live_prices_map"] = {
        "RELIANCE": {"symbol": "RELIANCE", "ltp": 2500.0, "change_pts": 10.0, "pct_change": 0.4, "prev_close": 2490.0}
    }
    res = client.get("/api/live_prices")
    assert res.status_code == 200
    data = res.json()
    assert "stocks" in data
    assert "indices" in data
    assert "btst_status" in data
    assert "data_feed_info" in data

def test_api_indices_endpoint_returns_required_fields():
    from app import cache_store
    cache_store["index_data"] = [
        {"index_name": "NIFTY50", "ltp": 24000.0, "change_pts": 100.0, "pct_change": 0.45, "prev_close": 23900.0},
        {"index_name": "BANKNIFTY", "ltp": 51000.0, "change_pts": 200.0, "pct_change": 0.40, "prev_close": 50800.0},
        {"index_name": "SENSEX", "ltp": 79000.0, "change_pts": 300.0, "pct_change": 0.38, "prev_close": 78700.0},
        {"index_name": "GIFTNIFTY", "ltp": 24050.0, "change_pts": 120.0, "pct_change": 0.50, "prev_close": 23930.0}
    ]
    res = client.get("/api/indices")
    assert res.status_code == 200
    data = res.json()
    assert "indices" in data
    assert "btst_status" in data
    idx_names = [idx.get("index_name") for idx in data["indices"]]
    for expected_idx in ["NIFTY50", "BANKNIFTY", "SENSEX", "GIFTNIFTY"]:
        assert expected_idx in idx_names, f"Missing index: {expected_idx}"

def test_api_performance_endpoint_returns_required_fields():
    res = client.get("/api/performance")
    assert res.status_code == 200
    data = res.json()
    assert "win_rate_pct" in data
    assert "prediction_accuracy_pct" in data
    assert "total_trades" in data
    assert "wins" in data
    assert "losses" in data

def test_api_chart_endpoint_returns_candles_for_stock_and_index(monkeypatch):
    import pandas as pd, numpy as np, yfinance as yf
    dates = pd.date_range("2026-08-10 09:15", periods=10, freq="5min")
    fake_df = pd.DataFrame({
        "Open": np.linspace(100, 105, 10),
        "High": np.linspace(101, 106, 10),
        "Low": np.linspace(99, 104, 10),
        "Close": np.linspace(100.5, 105.5, 10),
        "Volume": [1000] * 10
    }, index=dates)
    monkeypatch.setattr(yf, "download", lambda *a, **k: fake_df)

    res_stock = client.get("/api/chart/RELIANCE")
    assert res_stock.status_code == 200
    data_stock = res_stock.json()
    assert "candles" in data_stock
    assert len(data_stock["candles"]) > 0

    res_index = client.get("/api/chart/NIFTY50")
    assert res_index.status_code == 200
    data_index = res_index.json()
    assert "candles" in data_index
    assert len(data_index["candles"]) > 0

def test_api_lock_picks_and_evaluate_picks_endpoints(monkeypatch):
    from app import cache_store
    cache_store["data"] = [
        {"symbol": "RELIANCE", "raw_ticker": "RELIANCE.NS", "signal": "BTST (BUY)", "priority_level": "P1_HIGH", "close_price_325": 100.0, "predicted_gap_pct": 1.5, "ltp": 100.0}
    ]
    res_lock = client.post("/api/lock_picks", headers=auth_headers)
    assert res_lock.status_code == 200
    data_lock = res_lock.json()
    assert "status" in data_lock
    assert "message" in data_lock

    res_eval = client.post("/api/evaluate_picks", headers=auth_headers)
    assert res_eval.status_code == 200
    data_eval = res_eval.json()
    assert "status" in data_eval
    assert "message" in data_eval

def test_api_strategies_endpoint_returns_presets():
    res = client.get("/api/strategies")
    assert res.status_code == 200
    data = res.json()
    assert "strategies" in data
    assert len(data["strategies"]) >= 1
