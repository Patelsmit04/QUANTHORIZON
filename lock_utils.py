"""
Shared file-lock context manager — was implemented independently in fundamental_provider.py
and news_provider.py (Phase-1 audit finding #6), same check-exists / check-staleness /
write-lock / try-finally-remove logic, two different constant names for the same concept.
One copy here, both callers use it.
"""

import os
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger("LockUtils")


@contextmanager
def file_lock(lock_path: str, stale_after_seconds: float, label: str):
    """Guards against two concurrent runs of the same refresh job (e.g. a reload racing a
    manual trigger) stomping on the same cache file. A lock older than `stale_after_seconds`
    is assumed to be left over from a crashed/killed run, not a live one, and is taken over
    rather than blocking forever. Yields True if the lock was acquired (caller should do the
    work), False if another run is genuinely in progress (caller should skip)."""
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)

    if os.path.exists(lock_path):
        lock_age = time.time() - os.path.getmtime(lock_path)
        if lock_age < stale_after_seconds:
            logger.warning(f"[{label}] already in progress elsewhere (lock is {lock_age:.0f}s old) — skipping.")
            yield False
            return
        logger.warning(f"[{label}] stale lock ({lock_age:.0f}s old) — assuming a crashed run and proceeding.")

    with open(lock_path, "w") as f:
        f.write(str(time.time()))

    try:
        yield True
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass
