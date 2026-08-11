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
