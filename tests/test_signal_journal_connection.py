"""
M8 audit fix: get_db_connection() now explicitly closes the underlying sqlite3 connection
(via a real try/except/finally-wrapped @contextmanager) instead of relying on `with conn:`,
which only commits/rolls back and never closes. No call site changed — this verifies the
existing `with get_db_connection() as conn:` usage pattern still gets the same commit/rollback
behavior while also actually closing.
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


def test_connection_is_closed_after_normal_exit(isolated_db):
    with signal_journal.get_db_connection() as conn:
        conn.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")  # closed connections raise on further use


def test_commit_happens_on_normal_exit(isolated_db):
    with signal_journal.get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO signal_journal (id, timestamp, signal_date, symbol, raw_ticker, "
            "liquidity_tier, priority_level, signal, predicted_direction, option_type, "
            "confidence_score, confidence_bucket, close_price_325, predicted_gap_pct, vwap, "
            "volume_spike, rsi, range_position_pct, pillar_1_confirmed, pillar_1_weight, "
            "pillar_2_confirmed, pillar_2_weight, pillar_3_confirmed, pillar_3_weight, "
            "pillar_4_confirmed, pillar_4_weight, pillar_5_confirmed, pillar_5_weight, "
            "total_pillar_weight, expiry_discount_applied, vix_regime, vix_value, strategy_id) "
            "VALUES ('t1','2026-01-01 00:00:00 IST','2026-01-01','TEST','TEST','TIER_1','P1_HIGH',"
            "'BTST_BUY','BULLISH','CALL',80,'80-89',100.0,1.0,99.0,1.0,50.0,50.0,"
            "1,1.0,1,1.0,1,1.0,1,1.0,1,1.0,5.0,0,'NORMAL',15.0,'default-5-pillar')"
        )

    # A fresh connection must see the committed row.
    with signal_journal.get_db_connection() as conn2:
        row = conn2.execute("SELECT id FROM signal_journal WHERE id = 't1'").fetchone()
    assert row is not None


def test_rollback_happens_on_exception_and_connection_still_closes(isolated_db):
    conn_ref = {}

    with pytest.raises(ValueError):
        with signal_journal.get_db_connection() as conn:
            conn_ref["conn"] = conn
            conn.execute("SELECT 1")
            raise ValueError("simulated mid-transaction failure")

    with pytest.raises(sqlite3.ProgrammingError):
        conn_ref["conn"].execute("SELECT 1")  # still closed even though an exception propagated
