"""
M8 audit fix: the closing sequence's 3:14 PM SNAPSHOT step must never freeze a PRIOR day's
cached scan as if it were today's — background_scheduler_worker restores the last persisted
snapshot into cache_store unconditionally at startup, with no date check, so cache_store["data"]
can still hold yesterday's (or older) picks right after a restart, before today's first scan
has run. _snapshot_ready_stocks() is the guard closing_sequence's get_current_stocks callback
now goes through instead of reading cache_store["data"] directly.
"""
import app as appmod


def test_returns_empty_when_cached_scan_is_from_a_prior_day(monkeypatch):
    monkeypatch.setitem(appmod.cache_store, "data", [{"symbol": "OLDPICK", "signal": "BTST_BUY"}])
    monkeypatch.setitem(appmod.cache_store, "scan_summary", {"timestamp": "2026-08-01 15:20:00 IST"})

    result = appmod._snapshot_ready_stocks(today_date="2026-08-06")

    assert result == []


def test_returns_data_when_cached_scan_is_from_today(monkeypatch):
    todays_pick = {"symbol": "FRESHPICK", "signal": "BTST_BUY"}
    monkeypatch.setitem(appmod.cache_store, "data", [todays_pick])
    monkeypatch.setitem(appmod.cache_store, "scan_summary", {"timestamp": "2026-08-06 15:14:03 IST"})

    result = appmod._snapshot_ready_stocks(today_date="2026-08-06")

    assert result == [todays_pick]


def test_returns_empty_when_no_scan_summary_yet(monkeypatch):
    monkeypatch.setitem(appmod.cache_store, "data", None)
    monkeypatch.setitem(appmod.cache_store, "scan_summary", None)

    result = appmod._snapshot_ready_stocks(today_date="2026-08-06")

    assert result == []
