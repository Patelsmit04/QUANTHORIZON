"""
M8 audit fix: check_and_increment_budget()'s read-check-write cycle is now serialized via
json_file_lock, closing the TOCTOU race where concurrent requests could both read the same
"one slot left" count, both pass the check, and both fire a real billed Claude call while the
persisted counter only reflects one of them.
"""
import threading

import pytest

import clarification_budget as cb


@pytest.fixture(autouse=True)
def isolated_budget_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "BUDGET_FILE", str(tmp_path / "clarification_budget.json"))
    monkeypatch.setattr(cb, "MAX_CLARIFICATIONS_PER_DAY", 5)
    yield


def test_concurrent_calls_never_exceed_the_daily_cap():
    successes = []
    failures = []
    lock = threading.Lock()

    def attempt():
        try:
            cb.check_and_increment_budget()
            with lock:
                successes.append(1)
        except cb.ClarificationBudgetExceededError:
            with lock:
                failures.append(1)

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 5  # exactly the cap, never more, regardless of race timing
    assert len(failures) == 15
    status = cb.get_budget_status()
    assert status["used_today"] == 5
