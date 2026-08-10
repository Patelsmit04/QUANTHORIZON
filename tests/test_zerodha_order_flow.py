import pytest
from zerodha_order_flow_provider import (
    check_kite_token_validity,
    apply_tick_rule,
    calculate_depth_imbalance,
    generate_synthetic_order_flow,
    OrderFlowData
)
from order_flow_analyzer import check_closing_aggression


def test_kite_token_validity_unconfigured():
    res = check_kite_token_validity()
    assert "valid" in res
    assert res["valid"] is False
    assert res["status"] in ["UNCONFIGURED", "PLACEHOLDER", "EXPIRED_OR_INVALID"]


def test_apply_tick_rule_aggressor_inference():
    # Uptick -> Buyer initiated (+1)
    assert apply_tick_rule(100.0, 100.5, 0) == 1
    # Downtick -> Seller initiated (-1)
    assert apply_tick_rule(100.5, 100.0, 1) == -1
    # Same price -> Inherits prior direction (+1)
    assert apply_tick_rule(100.0, 100.0, 1) == 1
    # Same price -> Inherits prior direction (-1)
    assert apply_tick_rule(100.0, 100.0, -1) == -1


def test_calculate_5_level_depth_imbalance():
    depth_payload = {
        "buy": [
            {"price": 100.0, "quantity": 500},
            {"price": 99.9, "quantity": 300},
            {"price": 99.8, "quantity": 200},
            {"price": 99.7, "quantity": 100},
            {"price": 99.6, "quantity": 100},
        ],
        "sell": [
            {"price": 100.1, "quantity": 200},
            {"price": 100.2, "quantity": 200},
            {"price": 100.3, "quantity": 100},
            {"price": 100.4, "quantity": 50},
            {"price": 100.5, "quantity": 50},
        ]
    }
    res = calculate_depth_imbalance(depth_payload)
    assert res["bid_qty_5l"] == 1200
    assert res["ask_qty_5l"] == 600
    assert res["depth_ratio"] == 2.0
    assert res["bid_pct"] == 66.7
    assert res["ask_pct"] == 33.3


def test_check_closing_aggression_confirmed_setup():
    of_data = generate_synthetic_order_flow("RELIANCE", is_bullish=True)
    res = check_closing_aggression("RELIANCE", of_data, signal_type="BTST (BUY)", day_cvd_trend="BULLISH")

    assert res["verdict"] in ["confirmed", "confirmed_against_trend"]
    assert res["directional_bars_count"] >= 7
    assert res["breadth_ok"] is True
    assert "Confirmed Order Flow" in res["reason"]


def test_check_closing_aggression_vetoed_on_weak_bars():
    of_data = OrderFlowData("TEST")
    of_data.minute_bars = [
        {"minute": f"15:{15+i:02d}", "buy_volume": 1000, "sell_volume": 3000, "net_delta": -2000, "tick_count": 200}
        for i in range(10)
    ]
    of_data.depth_imbalance = {"bid_qty_5l": 1000, "ask_qty_5l": 3000, "depth_ratio": 0.33, "bid_pct": 25.0, "ask_pct": 75.0}

    # Signal is BUY, but order flow is heavily SELL (0 positive bars)
    res = check_closing_aggression("TEST", of_data, signal_type="BTST (BUY)", day_cvd_trend="BULLISH")
    assert res["verdict"] == "vetoed"
    assert res["directional_bars_count"] == 0
    assert "VETOED" in res["reason"]


def test_check_closing_aggression_handles_data_gap():
    of_data = generate_synthetic_order_flow("RELIANCE", is_bullish=True)
    of_data.had_data_gap = True  # Simulated WebSocket dropout (>15s)

    res = check_closing_aggression("RELIANCE", of_data, signal_type="BTST (BUY)", day_cvd_trend="BULLISH")
    assert res["verdict"] == "insufficient_data"
    assert "Data gap detected" in res["reason"]
