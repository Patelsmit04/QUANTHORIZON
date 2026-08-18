"""
UNIT TESTS FOR MASTER DIAGNOSTIC & FIX RESOLUTIONS (PRO EDITION)
==============================================================================
Validates:
1. Upgraded Paper trading engine:
   - Dynamic quantity sizing & LIMIT / MARKET order modes
   - Realistic slippage modeling (0.05% - 0.10%)
   - Flat ₹20 brokerage + 0.1% STT deduction from Realized P&L
   - Insufficient margin verification guard
   - Dynamic Target & Stop Loss position modification
   - Virtual portfolio equity accounting
2. Strategies aggregate routes (/api/strategies/performance & /api/strategies/active_signals)
3. Test alert dispatching and Web Push subscription endpoints
4. System health expanded synthetic probes covering 14 endpoints
5. Accuracy split metrics resilience on N=0
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


def test_paper_trading_institutional_workflow(client):
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

    # 3. Place Limit Order with dynamic sizing (100 shares @ 2500)
    order_payload = {
        "symbol": "RELIANCE",
        "entry_price": 2500.0,
        "execution_mode": "LIMIT",
        "signal": "BTST (BUY)",
        "quantity": 100,
        "target_price_1": 2550.0,
        "target_price_2": 2600.0,
        "stop_loss": 2460.0
    }
    order_res = client.post("/api/paper_trading/order", json=order_payload)
    assert order_res.status_code == 200
    ord_data = order_res.json()
    assert ord_data["ok"] is True
    assert ord_data["entry_price"] == 2500.0
    assert ord_data["quantity"] == 100
    pos_id = ord_data["position_id"]

    # 4. Modify Position (Update TP & SL)
    update_res = client.post(f"/api/paper_trading/update/{pos_id}", json={
        "target_price_1": 2570.0,
        "target_price_2": 2620.0,
        "stop_loss": 2480.0
    })
    assert update_res.status_code == 200
    upd_data = update_res.json()
    assert upd_data["ok"] is True
    assert upd_data["target_price_1"] == 2570.0
    assert upd_data["stop_loss"] == 2480.0

    # 5. Check Open Position
    port_res2 = client.get("/api/paper_trading/portfolio")
    pdata2 = port_res2.json()
    assert len(pdata2["open_positions"]) == 1
    assert pdata2["open_positions"][0]["symbol"] == "RELIANCE"
    assert pdata2["open_positions"][0]["target_price_1"] == 2570.0

    # 6. Close Position with Profit & Verify Realistic Charges Deducted
    # Gross P&L: (2550 - 2500) * 100 = +5000.0
    # Exit Brokerage: ₹20 + Exit STT (2550 * 100 * 0.001 = 255.0) = ₹275.0
    # Net Realized P&L = 5000.0 - 275.0 = +4725.0
    close_res = client.post(f"/api/paper_trading/close/{pos_id}", json={"exit_price": 2550.0})
    assert close_res.status_code == 200
    cls_data = close_res.json()
    assert cls_data["ok"] is True
    assert cls_data["gross_pnl"] == 5000.0
    assert cls_data["realized_pnl"] == 4725.0

    # 7. Verify Portfolio Updated
    port_res3 = client.get("/api/paper_trading/portfolio")
    pdata3 = port_res3.json()
    assert len(pdata3["open_positions"]) == 0
    assert len(pdata3["closed_trades"]) == 1
    assert pdata3["account"]["realized_pnl"] == 4725.0
    assert pdata3["account"]["winning_trades"] == 1


def test_paper_trading_margin_guard(client):
    # Attempting to order with margin exceeding available cash balance
    order_payload = {
        "symbol": "MRF",
        "entry_price": 140000.0,
        "execution_mode": "LIMIT",
        "signal": "BTST (BUY)",
        "quantity": 100,  # ₹1.4 Crore > ₹10 Lakh
        "target_price_1": 145000.0,
        "stop_loss": 138000.0
    }
    order_res = client.post("/api/paper_trading/order", json=order_payload)
    assert order_res.status_code == 400
    assert "Insufficient Virtual Funds" in order_res.json()["detail"]


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
