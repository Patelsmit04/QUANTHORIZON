"""
One-time migration: copies existing local data/*.json files and data/signal_journal.db into
the shared Postgres database (DATABASE_URL) introduced in M10/M11 — so switching the persistent
scanner host over to Postgres-backed storage doesn't lose existing signal/strategy/trade
history.

Usage (run once, from the repo root, on the machine that has the real local data/ directory):
    DATABASE_URL=postgres://... python scripts/migrate_to_postgres.py

Safe to re-run: every write here is an upsert (ON CONFLICT DO UPDATE / pg_write_json's own
upsert), so running this twice just re-syncs the same local data rather than erroring or
duplicating rows. Strictly read-only against the local files/DB — nothing here deletes or
modifies anything under data/.
"""
import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from env_utils import load_env_with_fallback  # noqa: E402
load_env_with_fallback(BASE_DIR)

# ---- Part 1: JSON-blob files -> the app_state key-value table ----
JSON_BLOB_FILES = {
    "strategies": "strategies.json",
    "trade_history": "trade_history.json",
    "last_market_scan": "last_market_scan.json",
    "index_btst_verdicts": "index_btst_verdicts.json",
    "active_pillar_weights": "active_pillar_weights.json",
    "pillar_weights_history": "pillar_weights_history.json",
    "paper_trades": "paper_trades.json",
    "clarification_budget": "clarification_budget.json",
    "stock_news_cache": "stock_news_cache.json",
}

# Ordered parent-before-child for the two FK relationships (signal_evaluations ->
# signal_journal, index_verdict_evaluations -> index_verdict_journal).
TABLE_CONFLICT_COLUMNS = {
    "signal_journal": "id",
    "signal_evaluations": "signal_id",
    "index_verdict_journal": "id",
    "index_verdict_evaluations": "verdict_id",
    "notifications": "id",
}


def migrate_json_blobs(data_dir: str, read_json, pg_write_json) -> None:
    print("=== Migrating JSON-blob files -> Postgres app_state table ===")
    for key, filename in JSON_BLOB_FILES.items():
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path):
            print(f"  [skip] {filename} — no local file yet.")
            continue
        data = read_json(path, default=None)
        if data is None:
            print(f"  [skip] {filename} — empty or unreadable.")
            continue
        pg_write_json(key, data)
        size_desc = f"{len(data)} item(s)" if isinstance(data, (list, dict)) else "1 value"
        print(f'  [ok]   {filename} -> app_state["{key}"] ({size_desc})')


def migrate_sqlite_tables(sqlite_db_path: str, get_pg_connection) -> None:
    print("=== Migrating SQLite signal_journal.db -> Postgres tables ===")
    if not os.path.exists(sqlite_db_path):
        print(f"  [skip] {sqlite_db_path} does not exist locally — nothing to migrate.")
        return

    sqlite_conn = sqlite3.connect(sqlite_db_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        for table, conflict_col in TABLE_CONFLICT_COLUMNS.items():
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  [skip] {table} — no local rows.")
                continue

            columns = list(rows[0].keys())
            col_list = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            update_cols = [c for c in columns if c != conflict_col]
            update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            upsert_sql = (
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_col}) DO UPDATE SET {update_clause}"
            )

            migrated = 0
            with get_pg_connection() as pg_conn:
                with pg_conn.cursor() as cur:
                    for row in rows:
                        cur.execute(upsert_sql, tuple(row[c] for c in columns))
                        migrated += 1
                pg_conn.commit()
            print(f"  [ok]   {table}: {migrated} row(s) migrated.")
    finally:
        sqlite_conn.close()


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL is not set. Set it in .env (or the environment) to the Postgres "
              "connection string you want to migrate INTO, then re-run this script.")
        return 1

    import json_utils
    import pg_utils
    from env_utils import DATA_DIR
    # Importing signal_journal (with DATABASE_URL set) self-initializes the Postgres schema —
    # same "initialize on import" pattern the module already uses for SQLite.
    import signal_journal  # noqa: F401

    migrate_json_blobs(DATA_DIR, json_utils.read_json, pg_utils.pg_write_json)
    print()
    migrate_sqlite_tables(os.path.join(DATA_DIR, "signal_journal.db"), pg_utils.get_pg_connection)
    print(
        "\nMigration complete. Make sure DATABASE_URL is set to this SAME connection string "
        "in both your local .env and the Vercel project's environment variables, then redeploy."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
