"""
M10: pg_utils.py is the opt-in Postgres backend a persistent-host scanner and a separate
stateless deployment (e.g. Vercel) share instead of local files. No real Postgres is required
for these tests — get_pg_connection() is mocked throughout, matching this repo's stated testing
strategy for the Postgres branch (see the migration plan).
"""
from unittest.mock import MagicMock

import pytest

import pg_utils


def _fake_connection():
    """A MagicMock conn whose .cursor() supports `with conn.cursor() as cur:` and records
    every execute() call for assertions."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_use_postgres_reflects_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert pg_utils.USE_POSTGRES is False  # set at import time; this just documents intent


def test_pg_read_json_returns_default_when_row_missing(monkeypatch):
    conn, cursor = _fake_connection()
    cursor.fetchone.return_value = None
    monkeypatch.setattr(pg_utils, "get_pg_connection", lambda: conn)

    result = pg_utils.pg_read_json("missing_key", default={"x": 1})

    assert result == {"x": 1}
    cursor.execute.assert_called_once_with("SELECT value FROM app_state WHERE key = %s", ("missing_key",))
    conn.close.assert_called_once()


def test_pg_read_json_returns_stored_value(monkeypatch):
    conn, cursor = _fake_connection()
    cursor.fetchone.return_value = [{"stocks": ["RELIANCE"]}]
    monkeypatch.setattr(pg_utils, "get_pg_connection", lambda: conn)

    result = pg_utils.pg_read_json("last_market_scan")

    assert result == {"stocks": ["RELIANCE"]}


def test_pg_write_json_upserts_and_commits_owned_connection(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(pg_utils, "get_pg_connection", lambda: conn)

    pg_utils.pg_write_json("strategies", {"a": 1})

    assert cursor.execute.call_count == 1
    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (key) DO UPDATE" in sql
    assert params[0] == "strategies"
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


def test_pg_key_lock_acquires_advisory_lock_and_commits_on_success(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(pg_utils, "get_pg_connection", lambda: conn)

    with pg_utils.pg_key_lock("strategies"):
        pass

    lock_call = cursor.execute.call_args_list[0]
    assert "pg_advisory_xact_lock(hashtext(%s))" in lock_call[0][0]
    assert lock_call[0][1] == ("strategies",)
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    conn.close.assert_called_once()


def test_pg_key_lock_rolls_back_on_exception(monkeypatch):
    conn, cursor = _fake_connection()
    monkeypatch.setattr(pg_utils, "get_pg_connection", lambda: conn)

    with pytest.raises(ValueError):
        with pg_utils.pg_key_lock("strategies"):
            raise ValueError("boom")

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    conn.close.assert_called_once()


def test_reads_and_writes_inside_lock_reuse_the_locked_connection(monkeypatch):
    """The whole point of pg_key_lock over a plain per-call connection: a read-modify-write
    cycle inside it must run on the SAME session that holds the advisory lock, not race a
    second session that never tried to acquire that lock at all."""
    lock_conn, lock_cursor = _fake_connection()
    lock_cursor.fetchone.return_value = [{"count": 1}]

    other_conn, _ = _fake_connection()
    connections_created = [lock_conn, other_conn]
    monkeypatch.setattr(pg_utils, "get_pg_connection", lambda: connections_created.pop(0))

    with pg_utils.pg_key_lock("clarification_budget"):
        result = pg_utils.pg_read_json("clarification_budget", default={})
        pg_utils.pg_write_json("clarification_budget", {"count": 2})

    assert result == {"count": 1}
    # Only ONE connection should ever have been created — read/write reused the lock's own.
    assert connections_created == [other_conn]
    # The read/write must NOT have closed or committed the shared connection themselves —
    # that's pg_key_lock's job on exit.
    assert lock_conn.close.call_count == 1  # closed exactly once, by pg_key_lock's own exit
    assert lock_conn.commit.call_count == 1  # committed exactly once, by pg_key_lock's own exit


def test_reads_and_writes_outside_any_lock_use_independent_connections(monkeypatch):
    made_connections = []

    def _make_conn():
        conn, _ = _fake_connection()
        made_connections.append(conn)
        return conn

    monkeypatch.setattr(pg_utils, "get_pg_connection", _make_conn)

    pg_utils.pg_read_json("a", default=None)
    pg_utils.pg_write_json("b", {"x": 1})

    assert len(made_connections) == 2
    for conn in made_connections:
        conn.close.assert_called_once()
