"""
M7 audit fix: apply_dynamic_pillar_weights() must refuse to re-apply the +/-15%/day cap twice
in the same day even if its caller's in-memory "already ran today" flag was reset by a
restart. The guard has to be disk-backed (checked against PILLAR_WEIGHTS_FILE's own
last_updated) rather than trusted from the caller.
"""
from datetime import date

import pytest

import walk_forward_validator as wfv
from json_utils import atomic_write_json


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(wfv, "PILLAR_WEIGHTS_FILE", str(tmp_path / "active_pillar_weights.json"))
    monkeypatch.setattr(wfv, "PILLAR_WEIGHTS_HISTORY_FILE", str(tmp_path / "pillar_weights_history.json"))
    yield


def test_already_applied_today_short_circuits_without_touching_db(monkeypatch):
    today_str = date.today().isoformat()
    atomic_write_json(wfv.PILLAR_WEIGHTS_FILE, {
        "weights": {"Pillar 1: Futures OI": 1.1},
        "last_updated": today_str,
    })

    def fail_if_called():
        raise AssertionError("get_db_connection should not be called once already applied today")

    monkeypatch.setattr(wfv, "get_db_connection", fail_if_called)

    result = wfv.apply_dynamic_pillar_weights()

    assert result["status"] == "ALREADY_APPLIED_TODAY"
    assert result["applied"] is False


def test_proceeds_normally_when_not_yet_applied_today(monkeypatch):
    class _FakeCursor:
        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return []  # < 30 rows -> INSUFFICIENT SAMPLE, exercising the real code path

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(wfv, "get_db_connection", lambda: _FakeConn())

    result = wfv.apply_dynamic_pillar_weights()

    assert result["applied"] is False
    assert result["status"] == "INSUFFICIENT SAMPLE (N < 30)"


# ---------------------------------------------------------------------------
# vectorbt Integration Tests
# ---------------------------------------------------------------------------

def test_vectorbt_signal_array_generation():
    """Verify _generate_signal_arrays produces correct boolean arrays from evaluate_signal."""
    import pandas as pd
    import numpy as np
    from vectorbt_backtester import _generate_signal_arrays

    # Create synthetic OHLC data
    n = 50
    dates = pd.date_range("2026-08-01", periods=n, freq="1D")
    prices = np.linspace(100, 120, n)
    df = pd.DataFrame({
        "Open": prices - 0.2,
        "High": prices + 1.0,
        "Low": prices - 1.0,
        "Close": prices + 0.2,
        "Volume": np.random.randint(1000, 5000, n),
    }, index=dates)

    # A strategy that always returns a BUY signal
    def always_buy(window):
        return {"signal": "BTST_BUY", "entry": float(window["Close"].iloc[-1]), "tp_pct": 2.0, "sl_pct": 1.0}

    result = _generate_signal_arrays(df, always_buy, lookback=10)
    assert "entries" in result
    assert "exits" in result
    assert "tp_pcts" in result
    assert "sl_pcts" in result
    assert len(result["entries"]) == n
    assert result["entries"].sum() > 0  # should have some entries


def test_vectorbt_backtest_returns_valid_metrics():
    """Verify backtest_strategy returns expected metric keys."""
    import pandas as pd
    import numpy as np
    from vectorbt_backtester import backtest_strategy, _fetch_ohlc

    # A strategy that never signals — should return NO_SIGNALS
    def never_signal(window):
        return None

    result = backtest_strategy(
        "RELIANCE.NS",
        never_signal,
        period="1mo",
        interval="1d",
    )

    # Should have all expected keys even on empty result
    expected_keys = [
        "symbol", "status", "total_bars", "total_entries", "total_trades",
        "win_rate_pct", "sharpe_ratio", "max_drawdown_pct", "engine",
    ]
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"

    assert result["engine"] == "vectorbt"


def test_vectorbt_empty_result_format():
    """Verify _empty_result returns zero-valued result with all required keys."""
    from vectorbt_backtester import _empty_result

    result = _empty_result("TEST.NS", "TEST_STATUS")
    assert result["symbol"] == "TEST.NS"
    assert result["status"] == "TEST_STATUS"
    assert result["engine"] == "vectorbt"
    assert result["win_rate_pct"] == 0.0
    assert result["sharpe_ratio"] == 0.0


def test_legacy_walk_forward_still_works(monkeypatch):
    """Verify legacy DB-based validation functions are preserved and callable."""
    class _FakeCursor:
        def execute(self, *a, **k):
            pass
        def fetchall(self):
            return []

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(wfv, "get_db_connection", lambda: _FakeConn())

    # Legacy SMC validation should return INSUFFICIENT_SAMPLE
    result = wfv._legacy_validate_smc_strategy_out_of_sample()
    assert result["status"] == "INSUFFICIENT_SAMPLE"
    assert result.get("engine") == "legacy_db_query"

    # Legacy walk-forward should return INSUFFICIENT SAMPLE
    result = wfv._legacy_run_walk_forward_validation()
    assert "INSUFFICIENT" in result["status"]

