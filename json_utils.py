"""
Shared atomic JSON read/write helpers.

Plain `open(path, "w")` + `json.dump` is NOT atomic — a concurrent reader can open the file
while the write is mid-flight and see truncated/partial JSON. json.load() then raises, and
every read site in this codebase catches that broadly and returns {} / None, which silently
looks like "no data" instead of "a write happened to be in progress." Writing to a temp file
and then os.replace()-ing it over the target (atomic on both POSIX and Windows) means any
reader always sees either the fully-old or the fully-new file, never a half-written one.
"""

import os
import json
from typing import Any


def atomic_write_json(filepath: str, data: Any):
    tmp_path = f"{filepath}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, filepath)


def read_json(filepath: str, default: Any = None) -> Any:
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
