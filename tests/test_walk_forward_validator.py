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
