import pytest
from datetime import datetime
from env_utils import get_ist_now, get_ist_today_str, IST
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_timezone_synchronization():
    now_ist = get_ist_now()
    assert str(now_ist.tzinfo) == "Asia/Kolkata" or "Asia/Kolkata" in str(now_ist.tzinfo)
    today_str = get_ist_today_str()
    assert len(today_str) == 10
    assert today_str.count("-") == 2

def test_market_status_endpoint():
    res = client.get("/api/market_status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert data["status"] in ["PRE_MARKET", "OPEN", "CLOSED", "HOLIDAY"]
    assert "timestamp" in data
    assert "IST" in data["timestamp"]

def test_order_basket_export_endpoint():
    res = client.get("/api/order_basket")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list) or isinstance(data, dict)
