"""
Shared file-lock context manager — was implemented independently in fundamental_provider.py
and news_provider.py (Phase-1 audit finding #6), same check-exists / check-staleness /
write-lock / try-finally-remove logic, two different constant names for the same concept.
One copy here, both callers use it.

M8 audit fix: acquisition used to be `if os.path.exists(lock_path): ... else: open(lock_path,
"w")` — a check-then-act race (TOCTOU), not atomic. Two processes landing at the same instant
(exactly the "reload racing a manual trigger" scenario this module exists to guard against)
could both see no lock and both proceed. `os.O_CREAT | os.O_EXCL` makes the common case (no
existing lock) a single atomic syscall that fails outright if the file already exists, instead
of a separate exists-check followed by a separate open.
"""

import os
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger("LockUtils")


def _try_create_lock_file(lock_path: str) -> bool:
    """Atomic create-if-absent. Returns False (without raising) if the file already exists —
    the only case this needs to distinguish from a genuine OS-level failure."""
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(str(time.time()))
    return True


@contextmanager
def file_lock(lock_path: str, stale_after_seconds: float, label: str):
    """Guards against two concurrent runs of the same refresh job (e.g. a reload racing a
    manual trigger) stomping on the same cache file. A lock older than `stale_after_seconds`
    is assumed to be left over from a crashed/killed run, not a live one, and is taken over
    rather than blocking forever. Yields True if the lock was acquired (caller should do the
    work), False if another run is genuinely in progress (caller should skip)."""
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)

    if not _try_create_lock_file(lock_path):
        try:
            lock_age = time.time() - os.path.getmtime(lock_path)
        except OSError:
            lock_age = 0.0  # lock vanished between our failed create and this check — treat as fresh/contended

        if lock_age < stale_after_seconds:
            logger.warning(f"[{label}] already in progress elsewhere (lock is {lock_age:.0f}s old) — skipping.")
            yield False
            return

        logger.warning(f"[{label}] stale lock ({lock_age:.0f}s old) — assuming a crashed run and taking over.")
        try:
            os.remove(lock_path)
        except OSError:
            pass
        if not _try_create_lock_file(lock_path):
            logger.warning(f"[{label}] lost the race to take over a stale lock — skipping.")
            yield False
            return

    try:
        yield True
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass
