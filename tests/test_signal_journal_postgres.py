"""
M11: signal_journal.py's SQLite tables move to Postgres when DATABASE_URL is set. The riskiest
part of that (confirmed by reading every query in the file) was translating SQLite-specific
`?` placeholders and INSERT OR IGNORE/REPLACE into Postgres `%s` + ON CONFLICT — these tests
verify that translation is actually correct, against a mocked psycopg connection (no real
Postgres required, matching this repo's stated testing strategy for the Postgres branch).
"""
from unittest.mock import MagicMock

import pytest

import signal_journal as sj


def _fake_connection():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor  # signal_journal's _PgConnCompat.cursor() wraps this
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return conn, cursor


def test_pg_cursor_compat_translates_placeholders():
    raw_cursor = MagicMock()
    wrapped = sj._PgCursorCompat(raw_cursor)

    wrapped.execute("SELECT * FROM notifications WHERE id = ? AND read = ?", ("abc", 0))

    raw_cursor.execute.assert_called_once_with(
        "SELECT * FROM notifications WHERE id = %s AND read = %s", ("abc", 0)
    )


def test_pg_conn_compat_execute_shortcut_mirrors_sqlite():
    raw_conn = MagicMock()
    raw_cursor = MagicMock()
    raw_conn.cursor.return_value = raw_cursor
    wrapped = sj._PgConnCompat(raw_conn)

    result_cursor = wrapped.execute("UPDATE notifications SET read = 1 WHERE id = ?", ("abc",))

    raw_cursor.execute.assert_called_once_with("UPDATE notifications SET read = 1 WHERE id = %s", ("abc",))
    assert isinstance(result_cursor, sj._PgCursorCompat)


def test_get_db_connection_uses_postgres_when_enabled(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    with sj.get_db_connection() as wrapped_conn:
        assert isinstance(wrapped_conn, sj._PgConnCompat)

    conn.commit.assert_called_once()
    conn.close.assert_called_once()


def test_get_db_connection_rolls_back_on_exception_when_postgres(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    with pytest.raises(ValueError):
        with sj.get_db_connection():
            raise ValueError("boom")

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    conn.close.assert_called_once()


def test_log_signal_entry_uses_on_conflict_do_nothing_when_postgres(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    ok = sj.log_signal_entry({"symbol": "RELIANCE", "signal": "BTST_BUY"}, vix_value=15.0, vix_regime="NORMAL")

    assert ok is True
    executed_sql = cursor.execute.call_args[0][0]
    assert "ON CONFLICT (id) DO NOTHING" in executed_sql
    assert "INSERT OR IGNORE" not in executed_sql
    assert "%s" in executed_sql
    assert "?" not in executed_sql


def test_log_index_verdict_uses_on_conflict_do_update_when_postgres(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    ok = sj.log_index_verdict({"index_name": "NIFTY50", "verdict": "Buy Call"}, {"raw": "data"})

    assert ok is True
    executed_sql = cursor.execute.call_args[0][0]
    assert "ON CONFLICT (id) DO UPDATE SET" in executed_sql
    assert "INSERT OR REPLACE" not in executed_sql
    # Every non-PK column from the table must be covered, or a real upsert would silently
    # leave stale data in whichever column got left out of the SET list.
    for col in ["verdict_date", "timestamp", "index_name", "raw_ticker", "price",
                "price_verified", "verdict", "confidence_level_pct", "expected_open_direction",
                "expected_open_points", "expected_range_low", "expected_range_high",
                "primary_reason", "invalidation_level", "highest_probability_trade_type",
                "full_verdict_json", "raw_pillar_inputs_json"]:
        assert f"{col} = EXCLUDED.{col}" in executed_sql, f"missing upsert column: {col}"


def test_log_notification_translates_placeholder_when_postgres(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    result = sj.log_notification("lock_complete", "Title", "Message")

    assert result["title"] == "Title"
    executed_sql = cursor.execute.call_args[0][0]
    assert "%s" in executed_sql
    assert "?" not in executed_sql


def test_evaluate_pending_signals_uses_on_conflict_do_update_when_postgres(monkeypatch):
    import pandas as pd

    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    pending_row = {
        "id": "sig1", "signal_date": "2026-01-01", "raw_ticker": "RELIANCE.NS",
        "close_price_325": 100.0, "predicted_gap_pct": 1.0, "predicted_direction": "BULLISH",
        "priority_level": "P1_HIGH", "symbol": "RELIANCE",
    }
    # First execute() (the unevaluated SELECT) returns our one pending row; only relevant call.
    cursor.fetchall.return_value = [pending_row]
    fake_candles = pd.DataFrame({"Open": [101.0, 101.5], "Close": [101.2, 101.6],
                                  "High": [101.5, 101.8], "Low": [100.8, 101.0]})
    monkeypatch.setattr(sj, "fetch_post_lock_candles", lambda *a, **k: fake_candles)

    result = sj.evaluate_pending_signals()

    assert result["evaluated_count"] == 1
    insert_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO signal_evaluations" in c.args[0]]
    assert len(insert_calls) == 1
    executed_sql = insert_calls[0].args[0]
    assert "ON CONFLICT (signal_id) DO UPDATE SET" in executed_sql
    assert "INSERT OR REPLACE" not in executed_sql
    for col in ["eval_date", "eval_timestamp", "next_open_915", "next_high", "next_low",
                "next_close_930", "actual_gap_pct", "is_direction_correct", "variance_error_pct",
                "directional_accuracy_score", "trade_taken", "est_entry_premium",
                "est_exit_premium", "spread_haircut_pct", "gross_pnl_pct", "net_pnl_pct",
                "is_trade_win"]:
        assert f"{col} = EXCLUDED.{col}" in executed_sql, f"missing upsert column: {col}"


def test_evaluate_pending_index_verdicts_uses_on_conflict_do_update_when_postgres(monkeypatch):
    import pandas as pd

    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    pending_row = {
        "id": "v1", "verdict_date": "2026-01-01", "raw_ticker": "^NSEI", "price": 22000.0,
        "verdict": "Buy Call", "expected_open_points": 50.0,
        "expected_range_low": 21950.0, "expected_range_high": 22100.0, "index_name": "NIFTY50",
    }
    cursor.fetchall.return_value = [pending_row]
    fake_candles = pd.DataFrame({"Open": [22050.0], "Close": [22060.0]})
    monkeypatch.setattr(sj, "fetch_post_lock_candles", lambda *a, **k: fake_candles)

    result = sj.evaluate_pending_index_verdicts()

    assert result["evaluated_count"] == 1
    insert_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO index_verdict_evaluations" in c.args[0]]
    assert len(insert_calls) == 1
    executed_sql = insert_calls[0].args[0]
    assert "ON CONFLICT (verdict_id) DO UPDATE SET" in executed_sql
    assert "INSERT OR REPLACE" not in executed_sql
    for col in ["eval_date", "eval_timestamp", "next_open_915", "next_close_930",
                "actual_gap_pct", "is_direction_correct", "variance_error_pct",
                "actual_move_points", "move_within_expected_range"]:
        assert f"{col} = EXCLUDED.{col}" in executed_sql, f"missing upsert column: {col}"


def test_init_journal_db_uses_postgres_schema_when_enabled(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(sj, "USE_POSTGRES", True)
    monkeypatch.setattr(sj, "get_pg_connection", lambda: conn)

    sj.init_journal_db()

    all_sql = " ".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "DOUBLE PRECISION" in all_sql
    assert "strategy_id TEXT NOT NULL DEFAULT 'default-5-pillar'" in all_sql
    # SQLite's ALTER TABLE...ADD COLUMN migration path must not run for a fresh Postgres schema.
    assert "ALTER TABLE" not in all_sql
