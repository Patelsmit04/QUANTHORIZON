"""
M8 audit fix: call_with_retry() now gates submission through a semaphore holding one permit
per real worker slot, released only when the underlying call actually finishes — not when a
caller merely stops waiting on it. A saturated pool now fails fast instead of silently queuing
new submissions behind already-stuck calls (which would otherwise eat into the new caller's own
timeout budget invisibly).
"""
import threading
import time

import net_utils


def test_saturated_pool_fails_fast_instead_of_queuing(monkeypatch):
    # Shrink the pool to 2 slots for a fast, deterministic test.
    monkeypatch.setattr(net_utils, "_MAX_WORKERS", 2)
    monkeypatch.setattr(net_utils, "_worker_slots", threading.BoundedSemaphore(2))

    release_gate = threading.Event()

    def hang():
        release_gate.wait(timeout=5)
        return "done"

    # Occupy both slots with calls that won't finish until we say so.
    t1 = threading.Thread(target=lambda: net_utils.call_with_retry(hang, label="hang-1", retries=0, timeout=10))
    t2 = threading.Thread(target=lambda: net_utils.call_with_retry(hang, label="hang-2", retries=0, timeout=10))
    t1.start()
    t2.start()
    time.sleep(0.1)  # let both actually acquire their slot and start running

    start = time.time()
    result = net_utils.call_with_retry(lambda: "should not run", label="third-call", retries=0, timeout=0.3)
    elapsed = time.time() - start

    assert result is None  # failed fast, not queued
    assert elapsed < 1.0  # bounded by the 0.3s timeout, not by waiting for a hung call to finish

    release_gate.set()
    t1.join()
    t2.join()


def test_worker_slot_is_released_after_completion(monkeypatch):
    monkeypatch.setattr(net_utils, "_MAX_WORKERS", 1)
    monkeypatch.setattr(net_utils, "_worker_slots", threading.BoundedSemaphore(1))

    first = net_utils.call_with_retry(lambda: "first", label="quick-1", retries=0, timeout=5)
    assert first == "first"

    # The slot must be free again for a second, sequential call.
    second = net_utils.call_with_retry(lambda: "second", label="quick-2", retries=0, timeout=5)
    assert second == "second"
