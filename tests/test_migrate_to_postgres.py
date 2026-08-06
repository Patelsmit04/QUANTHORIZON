"""
M12: scripts/migrate_to_postgres.py copies existing local data/*.json + signal_journal.db into
Postgres once, ahead of cutting a persistent host over to DATABASE_URL. Tested against mocks
(no real Postgres needed), same strategy as the rest of the Postgres-branch test suite.
"""
import json
import os
import sqlite3
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import migrate_to_postgres as migrate  # noqa: E402


def test_main_refuses_to_run_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert migrate.main() == 1


def test_migrate_json_blobs_reads_local_files_and_writes_each_key(tmp_path):
    data_dir = str(tmp_path)
    with open(os.path.join(data_dir, "strategies.json"), "w") as f:
        json.dump({"default-5-pillar": {"name": "Default"}}, f)
    with open(os.path.join(data_dir, "trade_history.json"), "w") as f:
        json.dump({"trades": [{"id": "t1"}]}, f)
    # paper_trades.json deliberately absent — must be skipped, not error.

    from json_utils import read_json
    pg_write_json = MagicMock()

    migrate.migrate_json_blobs(data_dir, read_json, pg_write_json)

    written_keys = {call.args[0] for call in pg_write_json.call_args_list}
    assert "strategies" in written_keys
    assert "trade_history" in written_keys
    assert "paper_trades" not in written_keys  # file didn't exist, correctly skipped
    strategies_call = next(c for c in pg_write_json.call_args_list if c.args[0] == "strategies")
    assert strategies_call.args[1] == {"default-5-pillar": {"name": "Default"}}


def test_migrate_sqlite_tables_skips_missing_db(tmp_path, capsys):
    migrate.migrate_sqlite_tables(str(tmp_path / "nonexistent.db"), get_pg_connection=MagicMock())
    assert "does not exist locally" in capsys.readouterr().out


def test_migrate_sqlite_tables_upserts_every_row_parent_before_child(tmp_path, monkeypatch):
    db_path = str(tmp_path / "signal_journal.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE signal_journal (id TEXT PRIMARY KEY, symbol TEXT)")
    conn.execute("CREATE TABLE signal_evaluations (signal_id TEXT PRIMARY KEY, net_pnl_pct REAL)")
    conn.execute("INSERT INTO signal_journal VALUES ('sig1', 'RELIANCE')")
    conn.execute("INSERT INTO signal_evaluations VALUES ('sig1', 2.5)")
    conn.commit()
    conn.close()

    executed_sql_by_table = {"signal_journal": [], "signal_evaluations": []}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            for table in executed_sql_by_table:
                if f"INSERT INTO {table}" in sql:
                    executed_sql_by_table[table].append((sql, params))

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

    def fake_get_pg_connection():
        return FakeConn()

    # Only these two tables exist in our minimal fake DB — a real run always has all 5
    # (init_journal_db() creates them all), so scope this test to just the FK pair that
    # matters for verifying migration order.
    monkeypatch.setattr(migrate, "TABLE_CONFLICT_COLUMNS", {"signal_journal": "id", "signal_evaluations": "signal_id"})
    migrate.migrate_sqlite_tables(db_path, fake_get_pg_connection)

    assert len(executed_sql_by_table["signal_journal"]) == 1
    assert len(executed_sql_by_table["signal_evaluations"]) == 1
    journal_sql, journal_params = executed_sql_by_table["signal_journal"][0]
    assert "ON CONFLICT (id) DO UPDATE SET" in journal_sql
    assert journal_params == ("sig1", "RELIANCE")
