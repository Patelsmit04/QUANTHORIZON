"""
Optional shared Postgres backend — lets a persistent-host scanner process (running the real
autonomous scheduler) and a separate stateless deployment (e.g. Vercel, which can't run that
scheduler at all — see env_utils.py) read/write the SAME state, instead of each having its own
local files that the other can never see.

Fully opt-in: everything here is only used when DATABASE_URL is set. With it unset, every
module that imports USE_POSTGRES from here falls through to its existing local
json_utils.py/signal_journal.py behavior, completely unchanged. This module intentionally
mirrors json_utils.py's exact function signatures (read_json/atomic_write_json/json_file_lock
-> pg_read_json/pg_write_json/pg_key_lock) so call sites only need a 2-line branch, not a
rewrite.

Storage model: one generic key-value table (`app_state`) holds every JSON-blob file that used
to live under data/*.json (one row per former file, keyed by a short name like "strategies" or
"trade_history") — see the migration plan for which files this covers and which stay
local-only. signal_journal.py's SQLite tables move to their own real Postgres tables
separately (higher-risk SQL-dialect work, not this module's concern).

Locking: json_utils.json_file_lock only ever protected against other THREADS in the same
process — meaningless once a second, separate process (a Vercel instance) can write the same
row. pg_key_lock uses a transaction-scoped Postgres advisory lock (pg_advisory_xact_lock),
keyed by a hash of the same string key used everywhere else here, so it works before the row
even exists and needs no separate unlock call (released automatically on commit/rollback).
"""

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

try:
    from psycopg.types.json import Jsonb
except ImportError:
    try:
        from psycopg2.extras import Json as Jsonb
    except ImportError:
        import json
        def Jsonb(data):
            return json.dumps(data)

USE_POSTGRES = False


def get_pg_connection():
    raise NotImplementedError("Postgres backend disabled — system runs exclusively on local storage.")


def init_app_state_schema() -> None:
    """Idempotent — safe to call on every startup, same as signal_journal.init_journal_db()."""
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        conn.commit()


# Tracks, per-thread, which app_state keys the CURRENT thread already holds an advisory lock
# for (and on which connection) — so pg_read_json/pg_write_json called from inside a
# `with pg_key_lock(key):` block reuse that same locked transaction instead of opening an
# unrelated connection that wouldn't actually be serialized against it. Thread-local (not a
# plain module dict) because FastAPI runs each synchronous request handler to completion on
# one worker thread, matching every other concurrency primitive already in this codebase
# (net_utils.py, app.py's _cache_lock) rather than introducing asyncio-flavored contextvars.
_local = threading.local()


def _get_locked_conn(key: str):
    return getattr(_local, "locked", {}).get(key)


def _set_locked_conn(key: str, conn) -> None:
    if not hasattr(_local, "locked"):
        _local.locked = {}
    _local.locked[key] = conn


def _clear_locked_conn(key: str) -> None:
    if hasattr(_local, "locked"):
        _local.locked.pop(key, None)


@contextmanager
def pg_key_lock(key: str) -> Iterator[None]:
    """
    Serializes an entire load-mutate-save cycle against one app_state row, across every
    process sharing this database — the direct cross-process equivalent of
    json_utils.json_file_lock. Use identically:

        with pg_key_lock("strategies"):
            store = pg_read_json("strategies", default={})
            store[strategy_id] = ...
            pg_write_json("strategies", store)
    """
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
        _set_locked_conn(key, conn)
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _clear_locked_conn(key)
        conn.close()


def pg_read_json(key: str, default: Any = None) -> Any:
    conn = _get_locked_conn(key)
    owns_conn = conn is None
    if owns_conn:
        conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM app_state WHERE key = %s", (key,))
            row = cur.fetchone()
        return row[0] if row else default
    finally:
        if owns_conn:
            conn.close()


def pg_write_json(key: str, data: Any) -> None:
    conn = _get_locked_conn(key)
    owns_conn = conn is None
    if owns_conn:
        conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_state (key, value, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                (key, Jsonb(data)),
            )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


# Initialize schema on module import, same pattern as signal_journal.init_journal_db() — but
# only when actually configured, unlike that one (which crashed on Vercel before DATA_DIR was
# fixed precisely because it ran unconditionally). No caller needs to remember to call this.
if USE_POSTGRES:
    init_app_state_schema()
