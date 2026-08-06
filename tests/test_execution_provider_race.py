"""
M8 audit fix: execute_signal()'s load-append-save cycle on paper_trades.json is now serialized
via json_file_lock — the 3:40 PM auto-lock thread and a manual
POST /api/strategies/{id}/execute used to be able to both load the same pre-mutation trade
list and each save their own version, silently discarding whichever ran first.
"""
import threading

import pytest

import execution_provider as ep


@pytest.fixture(autouse=True)
def isolated_trades_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "PAPER_TRADES_FILE", str(tmp_path / "paper_trades.json"))
    yield


def test_concurrent_executions_do_not_lose_trade_records():
    signal = {"symbol": "TESTSTOCK", "signal": "BTST_BUY", "option_type": "CALL", "confidence_score": 80}

    def fire(n):
        ep.execute_signal(signal, strategy_id=f"strategy-{n}")

    threads = [threading.Thread(target=fire, args=(n,)) for n in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    trades = ep.get_paper_trades(limit=100)
    assert len(trades) == 15  # every concurrent execution's record must survive
