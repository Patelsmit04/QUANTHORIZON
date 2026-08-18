import os
import sys
import pytest

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from synthetic_cvd_engine import (
    OrderFlowData,
    get_order_flow_data,
    process_tick,
)
from order_flow_analyzer import check_closing_aggression


def test_synthetic_order_flow_generation():
    of_data = get_order_flow_data("RELIANCE", signal_type="BTST (BUY)")
    assert of_data.symbol == "RELIANCE"
    assert len(of_data.minute_bars) == 10
    assert of_data.had_data_gap is False
    assert of_data.depth_imbalance["depth_ratio"] > 0


def test_check_closing_aggression_confirmed_setup():
    of_data = get_order_flow_data("RELIANCE", signal_type="BTST (BUY)")
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
    of_data = get_order_flow_data("RELIANCE", signal_type="BTST (BUY)")
    of_data.had_data_gap = True  # Simulated WebSocket dropout (>15s)

    res = check_closing_aggression("RELIANCE", of_data, signal_type="BTST (BUY)", day_cvd_trend="BULLISH")
    assert res["verdict"] == "insufficient_data"
    assert "Data gap detected" in res["reason"]
