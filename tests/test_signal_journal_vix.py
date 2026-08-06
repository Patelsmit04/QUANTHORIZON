"""
M7 audit fix: vix_value is a NOT NULL column, but fetch_india_vix() can now legitimately
return None. log_signal_entry() must substitute a distinguishable sentinel (-1.0) rather than
raise an IntegrityError or silently accept a fabricated value.
"""
import os
import sqlite3
import pytest

import signal_journal


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    db_file = os.path.join(data_dir, "signal_journal.db")
    monkeypatch.setattr(signal_journal, "DATA_DIR", data_dir)
    monkeypatch.setattr(signal_journal, "DB_FILE", db_file)
    signal_journal.init_journal_db()
    return db_file


def _fetch_row(db_file, signal_id):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM signal_journal WHERE id = ?", (signal_id,)).fetchone()
    conn.close()
    return row


def test_log_signal_entry_with_none_vix_stores_sentinel_not_null(isolated_db):
    stock = {"symbol": "TESTSTOCK", "signal": "BTST_BUY", "confidence_score": 80}

    ok = signal_journal.log_signal_entry(stock, vix_value=None, vix_regime="UNAVAILABLE")
    assert ok is True

    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    row = _fetch_row(isolated_db, f"{today}_{signal_journal.DEFAULT_STRATEGY_ID}_TESTSTOCK")

    assert row is not None
    assert row["vix_regime"] == "UNAVAILABLE"
    assert row["vix_value"] == -1.0  # never collides with a real (always-positive) VIX reading


def test_log_signal_entry_with_real_vix_unaffected(isolated_db):
    stock = {"symbol": "TESTSTOCK2", "signal": "STBT_SELL", "confidence_score": 70}

    ok = signal_journal.log_signal_entry(stock, vix_value=16.4, vix_regime="NORMAL")
    assert ok is True

    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    row = _fetch_row(isolated_db, f"{today}_{signal_journal.DEFAULT_STRATEGY_ID}_TESTSTOCK2")

    assert row["vix_regime"] == "NORMAL"
    assert row["vix_value"] == 16.4
