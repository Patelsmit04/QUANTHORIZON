"""
Shared atomic JSON read/write helpers.

Plain `open(path, "w")` + `json.dump` is NOT atomic — a concurrent reader can open the file
while the write is mid-flight and see truncated/partial JSON. json.load() then raises, and
every read site in this codebase catches that broadly and returns {} / None, which silently
looks like "no data" instead of "a write happened to be in progress." Writing to a temp file
and then os.replace()-ing it over the target (atomic on both POSIX and Windows) means any
reader always sees either the fully-old or the fully-new file, never a half-written one.

M8 audit fix: the temp path used to be a fixed f"{filepath}.tmp" shared by every writer to that
file. Two genuinely concurrent writers (e.g. the 3:40 PM auto-lock thread and a manual
POST /api/lock_picks both saving trade_history.json) could open/truncate/write the SAME temp
path at once, corrupting whichever write finishes last — os.replace() only guarantees the
final swap is atomic, not that two writers sharing one temp file don't stomp on each other
first. A pid+thread+uuid suffix gives every writer its own temp file, so os.replace() only
ever swaps in one writer's complete, uncorrupted output.

That alone still allows a "lost update": two writers can each read the old file, mutate their
own in-memory copy, and write back — whichever writes last silently discards the other's
change, since neither writer knew about the other's edit. json_file_lock() below serializes
the whole read-modify-write cycle for callers that need it. This app is a single process with
multiple threads (scheduler + request handlers), so an in-process lock is sufficient here — it
does not protect against a second OS process, which is what lock_utils.file_lock is for.

M8 audit fix (found while testing the above): on Windows, os.replace() onto a destination that
a SECOND thread is replacing at almost the same instant can raise a transient
`PermissionError: [WinError 5] Access is denied` — unlike POSIX rename(), Windows' underlying
MoveFileEx isn't immune to two concurrent replaces racing on the same target path, even though
each individual replace is itself atomic. This clears within microseconds once the other
thread's replace finishes, so a short bounded retry is enough — it does not mean the write is
unsafe, only that the specific instant it landed collided with another one.
"""

import os
import json
import time
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 0.02


def atomic_write_json(filepath: str, data: Any):
    tmp_path = f"{filepath}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(tmp_path, filepath)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_SECONDS)


def read_json(filepath: str, default: Any = None) -> Any:
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


_file_locks: dict = {}
_registry_lock = threading.Lock()


@contextmanager
def json_file_lock(filepath: str) -> Iterator[None]:
    """
    Serializes an entire load-mutate-save cycle against one JSON file, within this process.
    Wrap every read-modify-write sequence in this — e.g.:

        with json_file_lock(STRATEGIES_FILE):
            store = read_json(STRATEGIES_FILE, default={})
            store[strategy_id] = ...
            atomic_write_json(STRATEGIES_FILE, store)

    A single atomic_write_json()/read_json() call on its own doesn't need this — it's already
    torn-write-safe. This is for sequences where a second writer landing between the read and
    the write would silently discard the first writer's change.
    """
    normalized = os.path.abspath(filepath)
    with _registry_lock:
        lock = _file_locks.setdefault(normalized, threading.Lock())
    with lock:
        yield
