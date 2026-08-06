"""
M12: /api/scan and /api/indices used to fall back to running a live ~209-stock scan inline
whenever there was no cached snapshot — fine on a persistent host, but this always times out
on Vercel (no scheduler ever populates a cache there, and a live scan can't finish inside a
serverless function's execution limit). _can_run_live_scan_inline() gates that fallback; these
tests confirm the gate actually prevents the expensive call rather than just existing.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as appmod


@pytest.fixture
def client():
    return TestClient(appmod.app)


def test_can_run_live_scan_inline_true_without_vercel_env(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    assert appmod._can_run_live_scan_inline() is True


def test_can_run_live_scan_inline_false_under_vercel_env(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert appmod._can_run_live_scan_inline() is False


def test_scan_endpoint_never_calls_live_pipeline_when_gated(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": None, "data": None, "index_data": None, "timestamp": 0, "mode": "INITIALIZING"})
    monkeypatch.setattr(appmod, "load_last_market_scan", lambda: None)
    pipeline_spy = MagicMock(side_effect=AssertionError("run_full_scan_pipeline must not be called when gated"))
    monkeypatch.setattr(appmod, "run_full_scan_pipeline", pipeline_spy)

    r = client.get("/api/scan")

    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["stocks"] == []
    pipeline_spy.assert_not_called()


def test_scan_endpoint_serves_synced_snapshot_when_gated(client, monkeypatch):
    """The realistic M12 end state: Vercel has no in-memory cache, but Postgres (via
    load_last_market_scan) has whatever the persistent host last wrote — that must be served
    instead of the empty placeholder."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": None, "data": None, "index_data": None, "timestamp": 0, "mode": "INITIALIZING"})
    synced_snapshot = {"stocks": [{"symbol": "RELIANCE", "signal": "BTST_BUY"}], "indices": [], "timestamp": "2026-08-06 15:30:00 IST"}
    monkeypatch.setattr(appmod, "load_last_market_scan", lambda: synced_snapshot)
    pipeline_spy = MagicMock(side_effect=AssertionError("run_full_scan_pipeline must not be called when gated"))
    monkeypatch.setattr(appmod, "run_full_scan_pipeline", pipeline_spy)

    r = client.get("/api/scan")

    assert r.status_code == 200
    body = r.json()
    assert body["cache_hit"] is True
    assert body["stocks"][0]["symbol"] == "RELIANCE"
    pipeline_spy.assert_not_called()


def test_scan_endpoint_still_runs_live_pipeline_on_persistent_host(client, monkeypatch):
    """Regression check: the persistent host (no VERCEL env var) must keep its exact existing
    behavior — this is the path every pre-M12 test already exercised, confirmed unaffected."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": None, "data": None, "index_data": None, "timestamp": 0, "mode": "INITIALIZING"})
    monkeypatch.setattr(appmod, "load_last_market_scan", lambda: None)
    fake_response = {"stocks": [], "indices": [], "timestamp": "2026-08-06 15:30:00 IST"}
    pipeline_spy = MagicMock(return_value=fake_response)
    monkeypatch.setattr(appmod, "run_full_scan_pipeline", pipeline_spy)

    r = client.get("/api/scan")

    assert r.status_code == 200
    pipeline_spy.assert_called_once()


def test_indices_endpoint_never_calls_live_pipeline_when_gated(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": None, "data": None, "index_data": None, "timestamp": 0, "mode": "INITIALIZING"})
    monkeypatch.setattr(appmod, "load_last_market_scan", lambda: None)
    pipeline_spy = MagicMock(side_effect=AssertionError("run_full_scan_pipeline must not be called when gated"))
    monkeypatch.setattr(appmod, "run_full_scan_pipeline", pipeline_spy)

    r = client.get("/api/indices")

    assert r.status_code == 200
    assert r.json()["indices"] == []
    pipeline_spy.assert_not_called()


def test_indices_endpoint_serves_synced_snapshot_when_gated(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": None, "data": None, "index_data": None, "timestamp": 0, "mode": "INITIALIZING"})
    synced_snapshot = {"stocks": [], "indices": [{"index_name": "NIFTY50", "signal": "BTST_BUY"}]}
    monkeypatch.setattr(appmod, "load_last_market_scan", lambda: synced_snapshot)
    pipeline_spy = MagicMock(side_effect=AssertionError("run_full_scan_pipeline must not be called when gated"))
    monkeypatch.setattr(appmod, "run_full_scan_pipeline", pipeline_spy)

    r = client.get("/api/indices")

    assert r.status_code == 200
    assert r.json()["indices"][0]["index_name"] == "NIFTY50"
    pipeline_spy.assert_not_called()
