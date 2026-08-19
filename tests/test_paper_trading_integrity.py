import pytest
from fastapi.testclient import TestClient
import paper_trading_service
from app import app

client = TestClient(app)

def test_paper_portfolio_endpoint():
    response = client.get("/api/paper_trading/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "account" in data
    assert "open_positions" in data
    assert "closed_trades" in data
    assert data["account"]["starting_capital"] == 1000000.0

def test_anti_latency_arbitrage_and_slippage():
    # Reset account
    paper_trading_service.reset_paper_account(1000000.0)

    # Client tries to pass a low entry price of 10.0 for a 100.0 stock
    payload = {
        "symbol": "RELIANCE",
        "quantity": 250,
        "order_type": "BUY",
        "execution_mode": "MARKET",
        "entry_price": 10.0,  # Stale spoofed price
        "signal": "BTST (BUY)",
        "data_source": "SYNTHETIC_OFF_MARKET",
        "target_price_1": 3100.0,
        "stop_loss": 2800.0
    }

    response = client.post("/api/paper-trade/execute", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["ok"] is True
    # Verify slippage is applied (> 0)
    assert res["entry_price"] > 0
    # Verify entry charges are calculated (> ₹20)
    assert res["entry_charges"] >= 20.0

def test_insufficient_margin_rejection():
    # Attempt to buy 100,000 lots of NIFTY costing crores
    payload = {
        "symbol": "NIFTY 24500 CE",
        "quantity": 2500000,
        "order_type": "BUY",
        "execution_mode": "MARKET",
        "entry_price": 150.0,
        "signal": "CALL (NIFTY)"
    }
    response = client.post("/api/paper-trade/execute", json=payload)
    assert response.status_code == 400
    assert "Insufficient" in response.json()["detail"]

def test_auto_tp_sl_daemon_execution():
    paper_trading_service.reset_paper_account(1000000.0)
    # Open a position with TP1=100.0 and SL=50.0
    payload = {
        "symbol": "TESTSTOCK",
        "quantity": 10,
        "order_type": "BUY",
        "execution_mode": "LIMIT",
        "entry_price": 80.0,
        "target_price_1": 90.0,
        "target_price_2": 110.0,
        "stop_loss": 70.0
    }
    res = paper_trading_service.execute_paper_order(payload)
    assert res["ok"] is True
    pos_id = res["position_id"]

    # Close with TP1 hit
    close_res = paper_trading_service.close_paper_position(pos_id, exit_price=95.0)
    assert close_res["ok"] is True
    assert close_res["gross_pnl"] == 150.0  # (95 - 80) * 10
    assert close_res["realized_pnl"] < 150.0  # Net of exit fees
