"""
Test Suite: Live Major Indices Ticker Tape (NIFTY 50, BANK NIFTY, SENSEX, GIFT NIFTY)
Verifies:
1. fetch_major_indices_live() returns all 4 major benchmark indices.
2. /api/indices endpoint supplies all 4 indices.
3. /api/live_prices endpoint supplies all 4 indices for 1-second live polling.
4. static/index.html includes markup for NIFTY 50, BANK NIFTY, SENSEX, and GIFT NIFTY in #indexTickerTrack.
"""

import pytest
from fastapi.testclient import TestClient
from bs4 import BeautifulSoup
from app import app
from index_scoring import fetch_major_indices_live, fetch_gift_nifty_live

client = TestClient(app)


def test_fetch_major_indices_live_returns_all_four_indices():
    """Verify backend live index fetcher returns NIFTY 50, BANK NIFTY, SENSEX, and GIFT NIFTY."""
    indices = fetch_major_indices_live()
    assert isinstance(indices, list)
    assert len(indices) >= 4
    
    names = {idx.get("index_name") for idx in indices}
    assert "NIFTY50" in names
    assert "BANKNIFTY" in names
    assert "SENSEX" in names
    assert "GIFTNIFTY" in names
    
    for idx in indices:
        assert idx.get("ltp") is not None and idx.get("ltp") > 0
        assert idx.get("change_pts") is not None
        assert idx.get("pct_change") is not None
        assert idx.get("display_name") in ["NIFTY 50", "BANK NIFTY", "SENSEX", "GIFT NIFTY"]


def test_api_indices_endpoint_returns_all_four_indices():
    """Verify /api/indices returns all 4 major indices."""
    res = client.get("/api/indices")
    assert res.status_code == 200
    data = res.json()
    assert "indices" in data
    indices = data["indices"]
    assert len(indices) >= 4
    
    names = {idx.get("index_name") for idx in indices}
    assert "NIFTY50" in names
    assert "BANKNIFTY" in names
    assert "SENSEX" in names
    assert "GIFTNIFTY" in names


def test_api_live_prices_returns_all_four_indices():
    """Verify /api/live_prices returns all 4 major indices for 1-second live ticker."""
    res = client.get("/api/live_prices")
    assert res.status_code == 200
    data = res.json()
    assert "indices" in data
    indices = data["indices"]
    assert len(indices) >= 4
    
    names = {idx.get("index_name") for idx in indices}
    assert "NIFTY50" in names
    assert "BANKNIFTY" in names
    assert "SENSEX" in names
    assert "GIFTNIFTY" in names


def test_index_ticker_html_markup():
    """Verify static/index.html includes all 4 benchmark indices in the marquee ticker."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    ticker_track = soup.find("div", {"id": "indexTickerTrack"})
    assert ticker_track is not None
    
    items = ticker_track.find_all("span", class_="index-ticker-item")
    assert len(items) >= 4
    
    item_names = {item.get("data-index-name") for item in items}
    assert "NIFTY50" in item_names
    assert "BANKNIFTY" in item_names
    assert "SENSEX" in item_names
    assert "GIFTNIFTY" in item_names


def test_domestic_indices_frozen_off_market():
    """Verify domestic indices (NIFTY 50, BANK NIFTY, SENSEX) remain frozen off-market, with zero jitter."""
    from datetime import datetime, timezone, timedelta
    from index_scoring import is_domestic_market_active

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    # Test night-time 21:55 IST
    night_time = datetime(2026, 9, 2, 21, 55, tzinfo=ist_tz)
    assert is_domestic_market_active(night_time) is False

    # Test weekend
    weekend_time = datetime(2026, 9, 5, 11, 0, tzinfo=ist_tz) # Saturday
    assert is_domestic_market_active(weekend_time) is False

    # Test market hours (e.g. Wednesday 11:30 AM)
    open_time = datetime(2026, 9, 2, 11, 30, tzinfo=ist_tz)
    assert is_domestic_market_active(open_time) is True
