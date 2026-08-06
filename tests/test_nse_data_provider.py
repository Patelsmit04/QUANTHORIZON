"""
M7 audit fixes in nse_data_provider.py:
1. OI/delivery history now expires (STALE_AFTER_DAYS) instead of being served forever.
2. The 10-day OI baseline now reads the trailing window, not the front of the fetch window.
3. A real once-daily background refresh exists (refresh_nse_data_cache), guarded by a
   disk-backed "already ran today" check (was_nse_refresh_completed_today), instead of never
   being called with fetch_online=True anywhere.
"""
import os
from datetime import date, timedelta

import nse_data_provider as ndp
from json_utils import atomic_write_json


def _isolate_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ndp, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(ndp, "DELIVERY_HISTORY_FILE", str(data_dir / "nse_delivery_history.json"))
    monkeypatch.setattr(ndp, "OI_HISTORY_FILE", str(data_dir / "nse_oi_history.json"))
    monkeypatch.setattr(ndp, "NSE_REFRESH_META_FILE", str(data_dir / "nse_data_refresh_meta.json"))
    monkeypatch.setattr(ndp, "NSE_REFRESH_LOCK_FILE", str(data_dir / "nse_data_refresh.lock"))
    return data_dir


def test_age_in_days():
    today_str = date.today().isoformat()
    assert ndp._age_in_days(today_str) == 0
    old_str = (date.today() - timedelta(days=10)).isoformat()
    assert ndp._age_in_days(old_str) == 10
    assert ndp._age_in_days("not-a-date") == ndp.STALE_AFTER_DAYS + 1


def test_stale_delivery_history_reported_unavailable(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    stale_date = (date.today() - timedelta(days=ndp.STALE_AFTER_DAYS + 5)).isoformat()
    atomic_write_json(ndp.DELIVERY_HISTORY_FILE, {
        "TESTSTOCK": [{"date": stale_date, "delivery_pct": 45.0, "volume": 100000, "close": 100.0, "vwap": 99.0}]
    })

    result = ndp.get_per_stock_delivery_data("TESTSTOCK", fetch_online=False)

    assert result is None  # stale data must not be silently served as fresh


def test_fresh_delivery_history_served_with_age_metadata(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    today_str = date.today().isoformat()
    atomic_write_json(ndp.DELIVERY_HISTORY_FILE, {
        "TESTSTOCK": [{"date": today_str, "delivery_pct": 55.0, "volume": 100000, "close": 100.0, "vwap": 99.0}]
    })

    result = ndp.get_per_stock_delivery_data("TESTSTOCK", fetch_online=False)

    assert result is not None
    assert result["age_days"] == 0
    assert result["stale"] is False


def test_oi_baseline_uses_trailing_window_not_leading(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)

    # 20 ascending (oldest->newest) volume records: the first 10 day-over-day changes are all
    # tiny (~1%), the trailing 10 are all large (~50%). The pre-fix bug averaged the FIRST 10
    # changes (~1%); the fix must average the LAST 10 (~50%).
    volumes = [100000 + i * 500 for i in range(10)] + [1_000_000 * (1.5 ** i) for i in range(10)]
    records = [
        {"date": (date.today() - timedelta(days=20 - i)).isoformat(), "volume": int(v),
         "delivery_pct": 50.0, "close": 100.0, "vwap": 99.0}
        for i, v in enumerate(volumes)
    ]
    monkeypatch.setattr(ndp, "fetch_stock_delivery_history", lambda symbol, lookback_days=20: records)

    result = ndp.get_per_stock_oi_data("TESTSTOCK", fetch_online=False)

    assert result is not None
    # Manually compute the correct trailing-window expectation the same way the fixed code does.
    recent = volumes[-11:]
    expected_changes = [
        abs((recent[i] - recent[i - 1]) / recent[i - 1]) * 100.0
        for i in range(1, len(recent))
    ]
    expected_avg = round(sum(expected_changes) / len(expected_changes), 2)
    assert result["avg_10d_oi_pct"] == expected_avg
    assert result["avg_10d_oi_pct"] > 10.0  # would be ~1% under the old front-of-array bug


def test_refresh_cycle_sets_disk_backed_completion_flag(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    monkeypatch.setattr(ndp, "fetch_all_nse_data", lambda symbols, fetch_online=False: {
        s: {"oi_data": {"oi_pct_change": 1.0}, "delivery_data": {"delivery_pct": 50.0}} for s in symbols
    })

    assert ndp.was_nse_refresh_completed_today() is False

    result = ndp.refresh_nse_data_cache(["RELIANCE", "TCS"])

    assert result["fetched"] == 2
    assert ndp.was_nse_refresh_completed_today() is True
