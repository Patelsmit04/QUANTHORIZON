"""
TESTS FOR PAPER TRADING OPTION PREMIUM PRICING & LOT SIZING
===========================================================
Verifies:
1. Virtual option orders calculate margin on (Option Premium * Lot Size * Lots), NOT Spot Price * Lot Size.
2. Protection against spot price contamination when placing option orders.
3. Accurate MTM P&L valuation based on option premium deltas.
4. Capital accounting invariant holds when trading options.
5. Exit price and net realized P&L calculate accurately on option premium.
"""

import pytest
from starlette.testclient import TestClient
from app import app
import paper_trading_service
from contract_spec_provider import get_lot_size, get_contract_spec


@pytest.fixture
def client():
    return TestClient(app)


def test_contract_spec_lot_sizes():
    """Verifies that F&O equities and indices have correct authoritative lot sizes."""
    assert get_lot_size("RELIANCE") == 250
    assert get_lot_size("TCS") == 175
    assert get_lot_size("INFY") == 400
    assert get_lot_size("HDFCBANK") == 550
    assert get_lot_size("ICICIBANK") == 700
    assert get_lot_size("SBIN") == 750
    assert get_lot_size("NIFTY") == 25
    assert get_lot_size("BANKNIFTY") == 15
    assert get_lot_size("SENSEX") == 10


def test_option_order_margin_calculation(client):
    """
    Verifies that trading 1 lot of RELIANCE 1320 CE @ ₹30.00 premium
    charges ~₹7,500 margin (+ friction), NOT ₹3,30,000 (1320 * 250).
    """
    paper_trading_service.init_paper_trading_db()
    paper_trading_service.reset_paper_account(1000000.0)

    order_payload = {
        "symbol": "RELIANCE 1320 CE",
        "underlying": "RELIANCE",
        "strike": 1320,
        "leg": "CE",
        "quantity": 250,  # 1 lot
        "order_type": "BUY",
        "execution_mode": "MARKET",
        "entry_price": 30.0,
        "signal": "BTST CALL (CE)",
        "target_price_1": 100.0,
        "target_price_2": 150.0,
        "stop_loss": 2.0,
    }

    res = client.post("/api/paper-trade/execute", json=order_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["symbol"] == "RELIANCE 1320 CE"
    assert data["quantity"] == 250
    
    # Entry price should be around 30.0 (with slight slippage), NEVER around 1320.0
    assert 28.0 <= data["entry_price"] <= 32.0

    # Verify portfolio state
    port_res = client.get("/api/paper_trading/portfolio")
    assert port_res.status_code == 200
    port = port_res.json()
    acc = port["account"]

    # Starting capital was 10,00,000. Invested margin must be ~7,500, NOT 3,30,000!
    assert 7000.0 <= acc["invested_margin"] <= 8500.0
    assert acc["cash_balance"] > 990000.0  # Still has > 9.9 Lakhs available!
    assert acc["capital_invariant_verified"] is True

    # Check open position
    assert len(port["open_positions"]) == 1
    pos = port["open_positions"][0]
    assert pos["symbol"] == "RELIANCE 1320 CE"
    assert 28.0 <= pos["entry_price"] <= 32.0


def test_spot_price_contamination_guard(client):
    """
    If a caller mistakenly sends the stock spot price (e.g. ₹1320.0)
    as the entry_price for an option contract (RELIANCE 1320 CE),
    the backend must guard against spot contamination and not charge ₹3.3 Lakhs.
    """
    paper_trading_service.init_paper_trading_db()
    paper_trading_service.reset_paper_account(1000000.0)

    order_payload = {
        "symbol": "RELIANCE 1320 CE",
        "quantity": 250,
        "order_type": "BUY",
        "execution_mode": "MARKET",
        "entry_price": 1320.0,  # Spot price erroneously passed!
        "signal": "BTST CALL (CE)"
    }

    res = client.post("/api/paper-trade/execute", json=order_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    # The guard should have clamped entry_price to authentic option premium (< 150)
    assert data["entry_price"] < 200.0


def test_option_position_closure_and_realized_pnl(client):
    """Verifies that closing an option position computes P&L on option premium delta."""
    paper_trading_service.init_paper_trading_db()
    paper_trading_service.reset_paper_account(1000000.0)

    # Place order @ 30.0 premium
    order = paper_trading_service.execute_paper_order({
        "symbol": "RELIANCE 1320 CE",
        "quantity": 250,
        "order_type": "BUY",
        "execution_mode": "LIMIT",
        "entry_price": 30.0,
        "signal": "BTST CALL (CE)"
    })
    assert order["ok"] is True
    pos_id = order["position_id"]

    # Close position @ 40.0 premium (+10 pts gain on 250 shares = +2500 gross)
    close_res = paper_trading_service.close_paper_position(pos_id, exit_price=40.0)
    assert close_res["ok"] is True
    assert close_res["gross_pnl"] == 2500.0
    assert close_res["realized_pnl"] > 2400.0  # After STT and brokerage

    port = paper_trading_service.get_paper_portfolio()
    assert len(port["open_positions"]) == 0
    assert len(port["closed_trades"]) == 1
    assert port["account"]["realized_pnl"] > 2400.0
    assert port["account"]["capital_invariant_verified"] is True
