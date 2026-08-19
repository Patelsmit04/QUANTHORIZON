"""
TESTS FOR 4-BUTTON ACTION BAR, 1-SECOND LIVE OPTION CHAIN & DEMO TRADING MODAL
=============================================================================
Verifies:
1. /api/option-chain/{symbol} returns zero-latency structured option chain data.
2. /api/option-chain/{symbol} works for both indices (NIFTY) and F&O stocks (RELIANCE).
3. Option chain response includes lot_size, atm_strike, pcr, max_pain, and CE/PE leg metrics.
4. /api/paper-trade/execute validates virtual margins and places simulated positions.
5. static/index.html includes the 4-button action bar, optionChainModal, and optionsDemoTradeModal.
"""

import pytest
from starlette.testclient import TestClient
from app import app
import paper_trading_service


@pytest.fixture
def client():
    return TestClient(app)


def test_option_chain_endpoint_for_index(client):
    """Verifies index option chain endpoint structure."""
    response = client.get("/api/option-chain/NIFTY")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NIFTY"
    assert data["underlying_value"] > 0
    assert data["lot_size"] == 25
    assert data["atm_strike"] > 0
    assert "strikes" in data
    assert len(data["strikes"]) > 0
    
    first_strike = data["strikes"][0]
    assert "strike_price" in first_strike
    assert "ce" in first_strike
    assert "pe" in first_strike
    assert "ltp" in first_strike["ce"]
    assert "open_interest" in first_strike["ce"]


def test_option_chain_endpoint_for_stock(client):
    """Verifies stock option chain endpoint structure and lot sizes."""
    response = client.get("/api/option-chain/RELIANCE")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert data["underlying_value"] > 0
    assert data["lot_size"] == 250
    assert data["atm_strike"] > 0
    assert "pcr" in data
    assert "max_pain" in data


def test_options_paper_trading_execution(client):
    """Verifies virtual paper trading order execution for options contract."""
    # Reset / initialize paper account
    paper_trading_service.init_paper_trading_db()

    payload = {
        "symbol": "RELIANCE 3000 CE",
        "quantity": 250,
        "order_type": "BUY",
        "execution_mode": "MARKET",
        "entry_price": 45.0,
        "signal": "CALL (CE)",
        "notes": "Test Option Paper Trade"
    }

    response = client.post("/api/paper-trade/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["symbol"] == "RELIANCE 3000 CE"
    assert data["quantity"] == 250
    assert "position_id" in data


def test_options_paper_trading_margin_check(client):
    """Verifies that orders exceeding virtual cash balance are rejected."""
    payload = {
        "symbol": "NIFTY 25000 CE",
        "quantity": 100000,
        "order_type": "BUY",
        "execution_mode": "LIMIT",
        "limit_price": 500.0,  # ₹5,00,00,000 > ₹10,00,000 cash
        "entry_price": 500.0,
        "signal": "CALL (CE)",
    }

    response = client.post("/api/paper-trade/execute", json=payload)
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "Insufficient" in detail or "insufficient" in detail.lower()


def test_html_contains_option_chain_and_demo_modals():
    """Verifies that index.html and app.js have optionChainModal, optionsDemoTradeModal, and 4-button action bar."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="optionChainModal"' in html
    assert 'id="optionsDemoTradeModal"' in html
    assert 'ocMatrixTableBody' in html
    assert 'optTradeStrikeSelect' in html
    assert 'executeOptionsTradeBtn' in html
    assert 'stockDetailViewSwitcher' in html
    assert 'stockDetailAnalysisContainer' in html
    assert 'stockDetailChartContainer' in html
    assert 'modalViewSwitcher' in html
    assert 'modalAnalysisContainer' in html
    assert 'modalChartContainerWrap' in html
    assert 'modalOptionChainSymbol' in html

    with open("static/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert 'action-bar-4grid' in js
    assert 'btn-action-analysis' in js
    assert 'openOptionChainModal' in js
    assert 'openOptionsDemoTradeModal' in js
    assert 'setStockDetailView' in js
    assert 'setModalView' in js


def test_action_bar_contrast_and_view_routing():
    """Verifies Action Bar Tailwind classes, view routing, and dynamic option chain symbol binding."""
    with open("static/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Phase 1: Action Bar Tailwind Contrast Classes
    assert 'text-slate-500 hover:text-amber-600 hover:bg-slate-100' in js
    assert 'bg-amber-500 hover:bg-amber-600' in js
    assert 'bg-slate-50 border border-slate-300' in js

    # Phase 2: Mutually Exclusive View Toggling Logic
    assert "setStockDetailView" in js
    assert "setModalView" in js
    assert "stockDetailAnalysisContainer" in js
    assert "stockDetailChartContainer" in js

    # Phase 3: Dynamic Option Chain Modal Symbol Binding & Loading State
    assert "modalOptionChainSymbol" in js
    assert "Fetching live option chain for" in js
    assert "fetchOptionChain" in js

