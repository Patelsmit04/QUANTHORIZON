"""
M8 audit fix: file_lock() acquisition is now a single atomic O_CREAT|O_EXCL syscall for the
common case (no existing lock) instead of a check-exists-then-open TOCTOU race.
"""
import os
import time

from lock_utils import file_lock


def test_second_acquire_is_rejected_while_first_holds_it(tmp_path):
    lock_path = str(tmp_path / "job.lock")

    with file_lock(lock_path, stale_after_seconds=600, label="test") as acquired_1:
        assert acquired_1 is True
        assert os.path.exists(lock_path)

        with file_lock(lock_path, stale_after_seconds=600, label="test") as acquired_2:
            assert acquired_2 is False

    # Released after the outer `with` exits.
    assert not os.path.exists(lock_path)


def test_stale_lock_is_taken_over(tmp_path):
    lock_path = str(tmp_path / "job.lock")
    with open(lock_path, "w") as f:
        f.write(str(time.time()))
    old_time = time.time() - 3600
    os.utime(lock_path, (old_time, old_time))

    with file_lock(lock_path, stale_after_seconds=10, label="test") as acquired:
        assert acquired is True


def test_lock_released_on_exception(tmp_path):
    lock_path = str(tmp_path / "job.lock")

    try:
        with file_lock(lock_path, stale_after_seconds=600, label="test"):
            raise RuntimeError("simulated failure mid-job")
    except RuntimeError:
        pass

    assert not os.path.exists(lock_path)


def test_sequential_acquisitions_both_succeed(tmp_path):
    lock_path = str(tmp_path / "job.lock")

    with file_lock(lock_path, stale_after_seconds=600, label="test") as acquired_1:
        assert acquired_1 is True

    with file_lock(lock_path, stale_after_seconds=600, label="test") as acquired_2:
        assert acquired_2 is True
