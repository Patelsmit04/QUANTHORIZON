import pytest
from execution_provider import stage_order_payload, get_staged_orders

def test_stage_order_payload_formatting():
    signal = {
        "symbol": "RELIANCE",
        "raw_ticker": "RELIANCE.NS",
        "signal": "BTST (BUY)",
        "priority_level": "P1_HIGH",
        "conviction_level": "HIGH_CONVICTION",
        "option_type": "CALL (CE)",
        "ltp": 2500.0,
        "predicted_gap_pct": 2.0,
        "confidence_score": 92
    }
    staged = stage_order_payload(signal)
    assert staged["symbol"] == "RELIANCE"
    assert staged["action"] == "BUY"
    assert staged["option_type"] == "CALL (CE)"
    assert staged["target_profit_pct"] == 3.0
    assert staged["stop_loss_pct"] == 1.5
    assert staged["order_type"] == "AMO_LIMIT / PRE_MARKET"

def test_get_staged_orders_filters_p1_p2():
    picks = [
        {"symbol": "RELIANCE", "signal": "BTST (BUY)", "priority_level": "P1_HIGH", "ltp": 2500.0},
        {"symbol": "TCS", "signal": "WATCHLIST", "priority_level": "P3_LOW", "ltp": 3200.0},
        {"symbol": "INFY", "signal": "STBT (SELL)", "priority_level": "P2_MEDIUM", "ltp": 1500.0}
    ]
    staged = get_staged_orders(picks)
    assert len(staged) == 2
    symbols = [s["symbol"] for s in staged]
    assert "RELIANCE" in symbols
    assert "INFY" in symbols
    assert "TCS" not in symbols
