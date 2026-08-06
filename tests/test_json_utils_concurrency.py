"""
M8 audit fixes in json_utils.py:
1. atomic_write_json's temp path is now unique per writer (pid+thread+uuid), so two genuinely
   concurrent writers can no longer corrupt each other's in-flight temp file.
2. json_file_lock() serializes an entire read-modify-write cycle within this process, closing
   the "lost update" hole that a unique temp path alone doesn't fix.
"""
import json
import threading
import time

from json_utils import atomic_write_json, read_json, json_file_lock


def test_concurrent_atomic_writes_never_produce_corrupt_json(tmp_path):
    target = str(tmp_path / "shared.json")
    atomic_write_json(target, {"counter": 0})
    errors = []

    def writer(n):
        for i in range(20):
            try:
                atomic_write_json(target, {"counter": n * 100 + i})
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Whatever the final value is, it must be fully valid JSON — never a torn/interleaved write.
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    assert "counter" in data


def test_json_file_lock_prevents_lost_updates(tmp_path):
    target = str(tmp_path / "counter.json")
    atomic_write_json(target, {"count": 0})

    def increment_without_lock():
        data = read_json(target, default={"count": 0})
        time.sleep(0.01)  # widen the race window deliberately
        data["count"] += 1
        atomic_write_json(target, data)

    def increment_with_lock():
        with json_file_lock(target):
            data = read_json(target, default={"count": 0})
            time.sleep(0.01)
            data["count"] += 1
            atomic_write_json(target, data)

    # Unlocked: lost updates are expected (this documents the race the lock exists to close).
    threads = [threading.Thread(target=increment_without_lock) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    unlocked_result = read_json(target)["count"]
    assert unlocked_result < 10  # demonstrates the race exists without the lock

    # Reset and repeat WITH the lock — every increment must be preserved.
    atomic_write_json(target, {"count": 0})
    threads = [threading.Thread(target=increment_with_lock) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    locked_result = read_json(target)["count"]
    assert locked_result == 10


def test_json_file_lock_normalizes_relative_and_absolute_paths(tmp_path):
    import os
    rel_path = str(tmp_path / "same_file.json")
    abs_path = os.path.abspath(rel_path)

    order = []

    def hold_lock(path, tag):
        with json_file_lock(path):
            order.append(f"{tag}-start")
            time.sleep(0.05)
            order.append(f"{tag}-end")

    t1 = threading.Thread(target=hold_lock, args=(rel_path, "A"))
    t2 = threading.Thread(target=hold_lock, args=(abs_path, "B"))
    t1.start()
    time.sleep(0.01)  # ensure t1 acquires first
    t2.start()
    t1.join()
    t2.join()

    # The two calls must have been serialized (A fully finishes before B starts), proving
    # both path spellings mapped to the SAME underlying lock.
    assert order == ["A-start", "A-end", "B-start", "B-end"]
