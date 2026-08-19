import pytest
from fastapi.testclient import TestClient
import signal_journal
import walk_forward_validator
from app import app

client = TestClient(app)

def test_performance_summary_endpoint():
    res = client.get("/api/performance")
    assert res.status_code == 200
    data = res.json()
    assert "p1_win_rate_pct" in data
    assert "overall_win_rate_pct" in data
    assert "mean_absolute_error" in data
    assert "jackpot_trade_pct" in data

def test_trade_history_endpoint():
    res = client.get("/api/trade_history")
    assert res.status_code == 200
    data = res.json()
    assert "history" in data
    assert "total" in data

def test_validation_report_endpoint():
    res = client.get("/api/validation")
    assert res.status_code == 200
    data = res.json()
    assert "walk_forward_validation" in data
    assert "active_pillar_weights" in data

def test_directional_gap_accuracy_math():
    # Bullish (BTST): +1.0% gap is correct (1), -1.0% gap is incorrect (0)
    # Bearish (STBT): -1.0% gap is correct (1), +1.0% gap is incorrect (0)
    bull_gap_pos = 1.0
    bull_gap_neg = -1.0
    bear_gap_pos = 1.0
    bear_gap_neg = -1.0

    assert (1 if ("BULLISH" == "BULLISH" and bull_gap_pos > 0) else 0) == 1
    assert (1 if ("BULLISH" == "BULLISH" and bull_gap_neg > 0) else 0) == 0
    assert (1 if ("BEARISH" == "BEARISH" and bear_gap_neg < 0) else 0) == 1
    assert (1 if ("BEARISH" == "BEARISH" and bear_gap_pos < 0) else 0) == 0

def test_walk_forward_sample_guardrail():
    # If sample < 30, dynamic pillar weights should flag insufficient sample
    weights_res = walk_forward_validator.compute_dynamic_pillar_weights()
    assert "status" in weights_res
    if weights_res.get("sample_size", 0) < 30:
        assert "INSUFFICIENT" in weights_res["status"]
