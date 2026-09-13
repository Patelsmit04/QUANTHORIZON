import os
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_html_contains_all_7_sidebar_sections():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    sidebar_sections = [
        "scanner", "stocksNews", "globalNews", "institutionalFlow",
        "indices", "history", "strategies"
    ]

    for section in sidebar_sections:
        nav_item = soup.find("button", {"data-section": section})
        assert nav_item is not None, f"Missing sidebar navigation button for section: {section}"

def test_html_scanner_table_has_12_columns():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    table = soup.find("table", {"id": "scannerDataTable"})
    assert table is not None, "Missing scannerDataTable element"

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    expected_headers = [
        "RANK", "TICKER", "SIGNAL", "OPTION TYPE", "PRIORITY LEVEL",
        "CONFIDENCE SCORE", "EST. OVERNIGHT GAP", "LTP", "CHANGE (+/-)",
        "VOL SURGE", "RSI", "5-PILLAR WEIGHT", "ACTION"
    ]
    for h in expected_headers:
        assert h in headers, f"Missing header: {h} in scanner table"

def test_html_marquee_ticker_track_present():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    ticker_track = soup.find("div", {"id": "indexTickerTrack"})
    assert ticker_track is not None, "Missing indexTickerTrack element"

def test_api_strategies_endpoint_returns_presets():
    res = client.get("/api/strategies")
    assert res.status_code == 200
    data = res.json()
    assert "strategies" in data
    assert len(data["strategies"]) >= 1

def test_options_execution_panel_tradexo_design_system():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    opt_modal = soup.find("div", {"id": "optionsDemoTradeModal"})
    assert opt_modal is not None, "Missing optionsDemoTradeModal element"
    assert "tradexo-modal-backdrop" in opt_modal.get("class", [])

    card = opt_modal.find("div", class_="tradexo-options-card")
    assert card is not None, "Options execution modal must use tradexo-options-card class"

    # Verify tabular numbers on price feed elements
    und_ltp = soup.find("strong", {"id": "optTradeUnderlyingLtp"})
    assert und_ltp is not None
    assert "tradexo-mono-tabular" in und_ltp.get("class", [])

    prem_ltp = soup.find("strong", {"id": "optTradePremiumLtp"})
    assert prem_ltp is not None
    assert "tradexo-mono-tabular" in prem_ltp.get("class", [])

    # Verify Lucide icons presence in options modal
    lucide_elements = opt_modal.find_all(attrs={"data-lucide": True})
    assert len(lucide_elements) >= 5, "Options modal must utilize Lucide icons"

    # Verify CSS contains obsidian background definition
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "styles.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()
    assert "--tradexo-obsidian-bg: #09090b" in css_content

