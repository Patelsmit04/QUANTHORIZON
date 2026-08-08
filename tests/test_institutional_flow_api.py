"""
Integration check for GET /api/institutional_flow — confirms the route actually wires
block_deal_provider's deal storage/reconciliation/meta functions through FastAPI correctly,
not just that the underlying functions work in isolation (see test_block_deal_provider.py).

Uses TestClient WITHOUT the `with` context-manager form deliberately, same reasoning as
test_api_integration.py — avoids spawning the real background scheduler threads.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app as appmod
import block_deal_provider as bdp


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(bdp, "DAILY_FLOW_FILE", str(tmp_path / "institutional_flow_daily.json"))
    monkeypatch.setattr(bdp, "RECONCILIATION_FILE", str(tmp_path / "institutional_flow_reconciliation.json"))
    yield


@pytest.fixture
def client():
    return TestClient(appmod.app)


def test_institutional_flow_endpoint_empty_when_nothing_captured_today(client):
    r = client.get("/api/institutional_flow")
    assert r.status_code == 200
    body = r.json()
    assert body["deals"] == []
    assert body["meta"]["checkpoints_captured"] == []
    assert body["latest_reconciliation"] is None
    assert "shadow_mode" in body
    assert body["min_value_cr"] == bdp.MIN_VALUE_CR


def test_institutional_flow_endpoint_returns_deals_sorted_by_value(client):
    today_str = date.today().isoformat()
    deals = [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk", "deal_date": today_str, "as_of": "x"},
        {"symbol": "TCS", "side": "SELL", "value_cr": 90.0, "deal_type": "block", "deal_date": today_str, "as_of": "x"},
    ]
    bdp._persist_snapshot(today_str, "live_trigger", {}, deals=deals)

    r = client.get("/api/institutional_flow")
    body = r.json()
    assert [d["symbol"] for d in body["deals"]] == ["TCS", "RELIANCE"]
    assert body["meta"]["last_checkpoint"] == "live_trigger"


def test_institutional_flow_endpoint_filters_by_symbol(client):
    today_str = date.today().isoformat()
    deals = [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk", "deal_date": today_str, "as_of": "x"},
        {"symbol": "TCS", "side": "SELL", "value_cr": 90.0, "deal_type": "block", "deal_date": today_str, "as_of": "x"},
    ]
    bdp._persist_snapshot(today_str, "live_trigger", {}, deals=deals)

    r = client.get("/api/institutional_flow", params={"symbol": "RELIANCE"})
    body = r.json()
    assert len(body["deals"]) == 1
    assert body["deals"][0]["symbol"] == "RELIANCE"


def test_institutional_flow_endpoint_reports_latest_reconciliation(client):
    bdp._append_reconciliation_record({"date": "2026-08-07", "status": "CLEAN"})

    r = client.get("/api/institutional_flow")
    assert r.json()["latest_reconciliation"]["status"] == "CLEAN"
