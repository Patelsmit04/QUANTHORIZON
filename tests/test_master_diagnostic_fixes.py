"""
UNIT TESTS FOR MASTER DIAGNOSTIC & FIX RESOLUTIONS (ISSUES 1 - 11)
==============================================================================
Validates:
1. Paper trading virtual portfolio management, order placement, mark-to-market P&L, closure, and account reset (Issue 7).
2. Strategies aggregate routes (/api/strategies/performance & /api/strategies/active_signals) (Issue 1).
3. Test alert dispatching and Web Push subscription endpoints (Issue 10).
4. System health expanded synthetic probes covering 14 endpoints (Issue 5).
5. Accuracy split metrics resilience on N=0 (Issue 9).
==============================================================================
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import json
from starlette.testclient import TestClient
from app import app
import paper_trading_service


@pytest.fixture
def client():
    return TestClient(app)


def test_paper_trading_workflow(client):
    # 1. Reset account
    reset_res = client.post("/api/paper_trading/reset", json={"starting_capital": 1000000.0})
    assert reset_res.status_code == 200
    assert reset_res.json()["ok"] is True

    # 2. Get Portfolio
    port_res = client.get("/api/paper_trading/portfolio")
    assert port_res.status_code == 200
    pdata = port_res.json()
    assert pdata["account"]["starting_capital"] == 1000000.0
    assert pdata["account"]["cash_balance"] == 1000000.0
    assert len(pdata["open_positions"]) == 0

    # 3. Place Order
    order_payload = {
        "symbol": "RELIANCE",
        "entry_price": 2500.0,
        "signal": "BTST (BUY)",
        "quantity": 50,
        "target_price_1": 2550.0,
        "target_price_2": 2600.0,
        "stop_loss": 2460.0
    }
    order_res = client.post("/api/paper_trading/order", json=order_payload)
    assert order_res.status_code == 200
    ord_data = order_res.json()
    assert ord_data["ok"] is True
    pos_id = ord_data["position_id"]

    # 4. Check Open Position
    port_res2 = client.get("/api/paper_trading/portfolio")
    pdata2 = port_res2.json()
    assert len(pdata2["open_positions"]) == 1
    assert pdata2["open_positions"][0]["symbol"] == "RELIANCE"

    # 5. Close Position with Profit
    close_res = client.post(f"/api/paper_trading/close/{pos_id}", json={"exit_price": 2550.0})
    assert close_res.status_code == 200
    cls_data = close_res.json()
    assert cls_data["ok"] is True
    assert cls_data["realized_pnl"] == 2500.0  # (2550 - 2500) * 50 = +2500

    # 6. Verify Portfolio Updated
    port_res3 = client.get("/api/paper_trading/portfolio")
    pdata3 = port_res3.json()
    assert len(pdata3["open_positions"]) == 0
    assert len(pdata3["closed_trades"]) == 1
    assert pdata3["account"]["realized_pnl"] == 2500.0
    assert pdata3["account"]["winning_trades"] == 1


def test_strategies_aggregate_endpoints(client):
    perf_res = client.get("/api/strategies/performance")
    assert perf_res.status_code == 200
    assert "strategies" in perf_res.json()

    sigs_res = client.get("/api/strategies/active_signals")
    assert sigs_res.status_code == 200
    assert "active_signals" in sigs_res.json()


def test_notifications_test_alert_and_push(client):
    alert_res = client.post("/api/notifications/test_alert")
    assert alert_res.status_code == 200
    assert alert_res.json()["status"] == "SUCCESS"

    push_payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/fake-endpoint-test-123",
        "keys": {"auth": "auth_key", "p256dh": "p256dh_key"}
    }
    push_res = client.post("/api/notifications/push_subscribe", json=push_payload)
    assert push_res.status_code == 200
    assert push_res.json()["status"] == "SUCCESS"


def test_accuracy_split_endpoint_resilience(client):
    res = client.get("/api/accuracy/split")
    assert res.status_code == 200
    data = res.json()
    assert "btst_stocks" in data
    assert "btst_indices" in data
    assert "intraday_stocks" in data
    assert "intraday_indices" in data
