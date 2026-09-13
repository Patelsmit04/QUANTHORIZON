"""
COMPREHENSIVE VERIFICATION SCRIPT FOR ALL 3 USER REQUIREMENTS
============================================================
1. Live Index Tickers (NIFTY 50, SENSEX, BANK NIFTY, GIFT NIFTY) - Real values, zero fake jitter.
2. Zero Horizontal Scroll & Responsive Layout (no 100vw overflow, responsive tables).
3. Paper Trading Option Premium Pricing & Lot Size Calculation.
"""

import os
import re
import json
import pytest
from starlette.testclient import TestClient
from app import app
import paper_trading_service
from index_scoring import fetch_major_indices_live, fetch_gift_nifty_live
from contract_spec_provider import get_lot_size


@pytest.fixture
def client():
    return TestClient(app)


# =========================================================================
# REQUIREMENT 1: LIVE INDEX TICKERS (AUTHENTIC NSE/BSE, NO FAKE RANDOM JITTER)
# =========================================================================
def test_req1_live_indices_no_jitter():
    """Verify that fetch_major_indices_live and fetch_gift_nifty_live return authentic values with zero jitter."""
    with open("index_scoring.py", "r", encoding="utf-8") as f:
        src = f.read()

    # Ensure jitter_map and random.choice jitter are completely removed
    assert "jitter_map" not in src
    assert "random.choice([-1, 1])" not in src

    indices = fetch_major_indices_live()
    assert len(indices) >= 3
    
    nifty = next((x for x in indices if x.get("index_name") == "NIFTY50"), None)
    banknifty = next((x for x in indices if x.get("index_name") == "BANKNIFTY"), None)
    sensex = next((x for x in indices if x.get("index_name") == "SENSEX"), None)
    gift = fetch_gift_nifty_live()

    assert nifty is not None and nifty["ltp"] > 20000
    assert banknifty is not None and banknifty["ltp"] > 45000
    assert sensex is not None and sensex["ltp"] > 65000
    assert gift["ltp"] > 20000

    # Ensure two consecutive calls without cache expiry return identical authentic prints (no random fluctuation)
    indices_2 = fetch_major_indices_live()
    nifty_2 = next((x for x in indices_2 if x.get("index_name") == "NIFTY50"), None)
    assert nifty["ltp"] == nifty_2["ltp"]


# =========================================================================
# REQUIREMENT 2: ZERO HORIZONTAL SCROLL & RESPONSIVE CONTAINMENT
# =========================================================================
def test_req2_zero_horizontal_scroll_css():
    """Verify that 100vw rules causing Windows horizontal overflow have been completely eliminated."""
    with open("static/styles.css", "r", encoding="utf-8") as f:
        styles = f.read()
    with open("static/mobile-audit.css", "r", encoding="utf-8") as f:
        mobile = f.read()

    # Check that html, body, and app-shell do not use 100vw
    assert "width: 100vw" not in styles
    assert "max-width: 100vw" not in styles
    assert "width: 100vw" not in mobile

    # Check that overflow-x: hidden is present on body/html
    assert "overflow-x: hidden" in styles

    # Check table-container responsive scrolling
    assert ".table-container" in styles
    assert "overflow-x: auto" in styles


# =========================================================================
# REQUIREMENT 3: PAPER TRADING OPTION PREMIUM PRICING & LOT SIZING
# =========================================================================
def test_req3_paper_trading_option_premium_pricing(client):
    """Verify that paper trading calculates margin on Option Premium * Lot Size, not Spot Price."""
    paper_trading_service.init_paper_trading_db()
    paper_trading_service.reset_paper_account(1000000.0)

    # 1. Place RELIANCE 1320 CE option order (1 lot = 250 shares @ ₹28.50 premium)
    order_payload = {
        "symbol": "RELIANCE 1320 CE",
        "underlying": "RELIANCE",
        "strike": 1320,
        "leg": "CE",
        "quantity": 250,
        "entry_price": 28.50,
        "order_type": "BUY",
        "execution_mode": "MARKET",
        "signal": "BTST CALL (CE)",
        "target_price_1": 37.05,
        "target_price_2": 45.60,
        "stop_loss": 19.95,
    }

    res = client.post("/api/paper-trade/execute", json=order_payload)
    assert res.status_code == 200
    order_data = res.json()
    assert order_data["ok"] is True
    assert order_data["symbol"] == "RELIANCE 1320 CE"
    assert order_data["quantity"] == 250
    # Entry price must be option premium (~28.50), NOT stock spot price (~1320)
    assert 26.0 <= order_data["entry_price"] <= 31.0

    # 2. Check portfolio: Invested margin must be ~₹7,125 + charges, NOT ₹3,30,000!
    port = client.get("/api/paper_trading/portfolio").json()
    acc = port["account"]
    assert 6800.0 <= acc["invested_margin"] <= 8000.0
    assert acc["cash_balance"] > 990000.0
    assert acc["capital_invariant_verified"] is True

    # 3. Check position row in portfolio
    pos = next((p for p in port["open_positions"] if p["id"] == order_data["position_id"]), None)
    assert pos is not None
    assert pos["symbol"] == "RELIANCE 1320 CE"
    assert 26.0 <= pos["entry_price"] <= 31.0

    # 4. Close position with a ₹5 profit on premium
    close_price = order_data["entry_price"] + 5.0
    close_res = client.post(f"/api/paper_trading/close/{order_data['position_id']}", json={"exit_price": close_price})
    assert close_res.status_code == 200
    close_data = close_res.json()
    assert close_data["ok"] is True
    # Gross PnL = 5.0 * 250 = ₹1,250
    assert abs(close_data["gross_pnl"] - 1250.0) < 5.0
    assert close_data["realized_pnl"] > 1150.0  # Net after friction


def test_req3_frontend_wiring():
    """Verify that index.html and app.js have the required buttons, modals, and tables."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    with open("static/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Verify NEW OPTION TRADE button in index.html
    assert 'id="btnPaperNewTrade"' in html
    assert 'NEW OPTION TRADE' in html

    # Verify paper table columns
    assert 'CONTRACT / SYMBOL' in html
    assert 'LOTS &amp; QTY' in html
    assert 'ENTRY PREMIUM' in html
    assert 'LIVE PREMIUM' in html

    # Verify options demo trade modal
    assert 'id="optionsDemoTradeModal"' in html
    assert 'optTradeStrikeSelect' in html
    assert 'optLotsInput' in html
    assert 'executeOptionsTradeBtn' in html

    # Verify JS wiring
    assert 'FO_LOT_SIZE_MAP' in js
    assert 'getInstrumentLotSize' in js
    assert 'openOptionsDemoTradeModal' in js
    assert 'btnPaperNewTrade' in js
    assert 'window.openOrderTicketModal' in js
