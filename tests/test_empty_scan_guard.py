"""
M13 audit fix: a transient yfinance batch-download failure (timeout, or Yahoo Finance
rate-limiting/blocking the host's outbound IP — common on shared cloud IP ranges) makes
fetch_raw_stock_universe() return no usable data, which scores down to an empty `stocks` list.
_run_full_scan_pipeline_impl() used to persist that empty result unconditionally, permanently
overwriting a perfectly good prior snapshot with all-zero counts until the next successful scan
happened to land. These tests confirm the guard: an empty scan is only ever persisted when
there's no better cached snapshot to fall back on.
"""
from unittest.mock import MagicMock

import pytest

import app as appmod


@pytest.fixture(autouse=True)
def stub_pipeline_dependencies(monkeypatch):
    """Stub every collaborator of _run_full_scan_pipeline_impl except the two under test
    (score_stock_universe's output and cache_store's prior state)."""
    monkeypatch.setattr(appmod, "fetch_raw_stock_universe", lambda: {})
    monkeypatch.setattr(appmod, "list_strategies", lambda active_only=True: [])
    monkeypatch.setattr(appmod, "get_strategy", lambda sid: {"id": sid})
    monkeypatch.setattr(appmod, "fetch_raw_index_universe", lambda: {})
    monkeypatch.setattr(appmod, "score_index_universe", lambda raw, strat: [])
    monkeypatch.setattr(appmod.TradeHistoryManager, "load_data", staticmethod(lambda: {
        "win_rate_pct": 0.0, "prediction_accuracy_pct": 92.5, "total_trades": 0, "avg_gap_pct": 0.0,
    }))
    monkeypatch.setattr(appmod, "get_market_schedule_info", lambda: {"mode": "5-MIN REGULAR SCAN", "status": "OPEN"})
    monkeypatch.setattr(appmod, "annotate_bestest_5", lambda stocks: stocks)
    monkeypatch.setattr(appmod, "annotate_depth_analysis", lambda stocks: stocks)


def test_empty_scan_keeps_existing_good_snapshot(monkeypatch):
    monkeypatch.setattr(appmod, "score_stock_universe", lambda raw, strat: [])
    good_snapshot = {"stocks": [{"symbol": "RELIANCE"}], "total_scanned": 1}
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": good_snapshot, "data": [{"symbol": "RELIANCE"}]})
    save_spy = MagicMock()
    monkeypatch.setattr(appmod, "save_last_market_scan", save_spy)

    result = appmod._run_full_scan_pipeline_impl()

    assert result is good_snapshot
    save_spy.assert_not_called()


def test_empty_scan_persists_when_no_prior_snapshot_exists(monkeypatch):
    """First-ever run (nothing cached yet) has no better option than persisting the empty
    result — unchanged from pre-fix behavior."""
    monkeypatch.setattr(appmod, "score_stock_universe", lambda raw, strat: [])
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": None, "data": None})
    save_spy = MagicMock()
    monkeypatch.setattr(appmod, "save_last_market_scan", save_spy)

    result = appmod._run_full_scan_pipeline_impl()

    assert result["total_scanned"] == 0
    save_spy.assert_called_once()


def test_nonempty_scan_still_overwrites_prior_snapshot(monkeypatch):
    """Regression check: a real, successful scan must still replace the cached snapshot as
    before — the guard only applies when the new scan is empty."""
    new_stock = {"symbol": "TCS", "priority_level": "P3_LOW", "signal": "NEUTRAL", "volume_spike": 1.0}
    monkeypatch.setattr(appmod, "score_stock_universe", lambda raw, strat: [new_stock])
    good_snapshot = {"stocks": [{"symbol": "RELIANCE"}], "total_scanned": 1}
    monkeypatch.setattr(appmod, "cache_store", {"scan_summary": good_snapshot, "data": [{"symbol": "RELIANCE"}]})
    save_spy = MagicMock()
    monkeypatch.setattr(appmod, "save_last_market_scan", save_spy)

    result = appmod._run_full_scan_pipeline_impl()

    assert result["total_scanned"] == 1
    assert result["stocks"][0]["symbol"] == "TCS"
    save_spy.assert_called_once()
