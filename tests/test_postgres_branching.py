"""
M10: confirms each of the 9 JSON-blob modules actually takes the Postgres path when
USE_POSTGRES is true, calling pg_read_json/pg_write_json/pg_key_lock with the right key —
not just that the local-file path still works (the rest of the suite already covers that
extensively, unaffected since USE_POSTGRES defaults to False throughout it).
"""
from unittest.mock import MagicMock

import pytest

import strategy_manager as sm
import execution_provider as ep
import clarification_budget as cb
import walk_forward_validator as wfv
import news_provider as np_
import app as appmod


@pytest.fixture
def fake_pg_key_lock():
    """A no-op context manager standing in for pg_key_lock — we only need to prove the right
    key was requested, not exercise real locking (already covered by test_pg_utils.py)."""
    from contextlib import contextmanager

    calls = []

    @contextmanager
    def _lock(key):
        calls.append(key)
        yield

    return _lock, calls


def test_strategy_manager_uses_postgres_when_enabled(monkeypatch, fake_pg_key_lock):
    lock_fn, lock_calls = fake_pg_key_lock
    monkeypatch.setattr(sm, "USE_POSTGRES", True)
    monkeypatch.setattr(sm, "pg_key_lock", lock_fn)
    monkeypatch.setattr(sm, "pg_read_json", MagicMock(return_value={"strategies": "here"}))
    monkeypatch.setattr(sm, "pg_write_json", MagicMock())

    assert sm._load_all() == {"strategies": "here"}
    sm.pg_read_json.assert_called_once_with("strategies", default={})

    sm._save_all({"a": 1})
    sm.pg_write_json.assert_called_once_with("strategies", {"a": 1})

    with sm._state_lock():
        pass
    assert lock_calls == ["strategies"]


def test_execution_provider_uses_postgres_when_enabled(monkeypatch, fake_pg_key_lock):
    lock_fn, lock_calls = fake_pg_key_lock
    monkeypatch.setattr(ep, "USE_POSTGRES", True)
    monkeypatch.setattr(ep, "pg_key_lock", lock_fn)
    monkeypatch.setattr(ep, "pg_read_json", MagicMock(return_value=[{"order_id": "x"}]))
    monkeypatch.setattr(ep, "pg_write_json", MagicMock())

    assert ep._load_trades() == [{"order_id": "x"}]
    ep.pg_read_json.assert_called_once_with("paper_trades", default=[])

    ep._save_trades([{"order_id": "y"}])
    ep.pg_write_json.assert_called_once_with("paper_trades", [{"order_id": "y"}])

    with ep._state_lock():
        pass
    assert lock_calls == ["paper_trades"]


def test_clarification_budget_uses_postgres_when_enabled(monkeypatch, fake_pg_key_lock):
    lock_fn, lock_calls = fake_pg_key_lock
    monkeypatch.setattr(cb, "USE_POSTGRES", True)
    monkeypatch.setattr(cb, "pg_key_lock", lock_fn)
    monkeypatch.setattr(cb, "pg_read_json", MagicMock(return_value={"count": 3}))
    monkeypatch.setattr(cb, "pg_write_json", MagicMock())

    assert cb._load() == {"count": 3}
    cb._save({"count": 4})
    cb.pg_write_json.assert_called_once_with("clarification_budget", {"count": 4})

    with cb._state_lock():
        pass
    assert lock_calls == ["clarification_budget"]


def test_walk_forward_validator_uses_postgres_when_enabled(monkeypatch):
    monkeypatch.setattr(wfv, "USE_POSTGRES", True)
    monkeypatch.setattr(wfv, "pg_read_json", MagicMock(return_value={"weights": {}}))
    monkeypatch.setattr(wfv, "pg_write_json", MagicMock())

    assert wfv._load_pillar_weights() == {"weights": {}}
    wfv.pg_read_json.assert_called_once_with("active_pillar_weights", default=None)

    wfv._save_pillar_weights({"weights": {"Pillar 1: Futures OI": 1.1}})
    wfv.pg_write_json.assert_called_once_with("active_pillar_weights", {"weights": {"Pillar 1: Futures OI": 1.1}})

    wfv.pg_read_json.reset_mock()
    monkeypatch.setattr(wfv, "pg_read_json", MagicMock(return_value=[{"date": "2026-01-01"}]))
    assert wfv._load_weight_history() == [{"date": "2026-01-01"}]
    wfv.pg_read_json.assert_called_once_with("pillar_weights_history", default=[])


def test_news_provider_uses_postgres_when_enabled(monkeypatch):
    monkeypatch.setattr(np_, "USE_POSTGRES", True)
    monkeypatch.setattr(np_, "pg_read_json", MagicMock(return_value={"RELIANCE": {}}))
    monkeypatch.setattr(np_, "pg_write_json", MagicMock())

    assert np_._load_news_cache() == {"RELIANCE": {}}
    np_._save_news_cache({"TCS": {}})
    np_.pg_write_json.assert_called_once_with("stock_news_cache", {"TCS": {}})


def test_app_trade_history_uses_postgres_when_enabled(monkeypatch, fake_pg_key_lock):
    lock_fn, lock_calls = fake_pg_key_lock
    monkeypatch.setattr(appmod, "USE_POSTGRES", True)
    monkeypatch.setattr(appmod, "pg_key_lock", lock_fn)
    monkeypatch.setattr(appmod, "pg_read_json", MagicMock(return_value={"trades": []}))
    monkeypatch.setattr(appmod, "pg_write_json", MagicMock())

    assert appmod.TradeHistoryManager.load_data() == {"trades": []}
    appmod.TradeHistoryManager.save_data({"trades": [1]})
    saved_key, saved_value = appmod.pg_write_json.call_args[0]
    assert saved_key == "trade_history"
    assert saved_value["trades"] == [1]
    assert "last_updated" in saved_value

    with appmod.TradeHistoryManager._state_lock():
        pass
    assert lock_calls == ["trade_history"]


def test_app_last_market_scan_uses_postgres_when_enabled(monkeypatch):
    monkeypatch.setattr(appmod, "USE_POSTGRES", True)
    monkeypatch.setattr(appmod, "pg_read_json", MagicMock(return_value={"stocks": []}))
    monkeypatch.setattr(appmod, "pg_write_json", MagicMock())

    assert appmod.load_last_market_scan() == {"stocks": []}
    appmod.pg_read_json.assert_called_once_with("last_market_scan", default=None)

    appmod.save_last_market_scan({"stocks": [1]})
    appmod.pg_write_json.assert_called_once_with("last_market_scan", {"stocks": [1]})


def test_app_index_verdicts_uses_postgres_when_enabled(monkeypatch):
    monkeypatch.setattr(appmod, "USE_POSTGRES", True)
    monkeypatch.setattr(appmod, "pg_read_json", MagicMock(return_value={"verdicts": {}}))
    monkeypatch.setattr(appmod, "pg_write_json", MagicMock())

    assert appmod._load_index_verdicts() == {"verdicts": {}}
    appmod.pg_read_json.assert_called_once_with("index_btst_verdicts", default={})

    appmod._save_index_verdicts({"verdicts": {"NIFTY50": {}}})
    appmod.pg_write_json.assert_called_once_with("index_btst_verdicts", {"verdicts": {"NIFTY50": {}}})
