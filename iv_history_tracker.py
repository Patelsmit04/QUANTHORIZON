"""
20-DAY ATM-IV HISTORY — for Strategy F ("Volatility Straddle")
==================================================================
Strategy F needs "current IV in the lower 10th percentile of its 20-day IV range." No IV
history exists anywhere in this codebase before this module, and there is no way to backfill
it — it has to accumulate one real snapshot per asset per day, going forward, starting from
whenever this ships. get_iv_percentile() returns None (FAIL LOUD, matching every other
provider in this codebase) until 20 real days exist; it will not estimate a percentile from
partial history. This means Strategy F will not produce a real alert for ~20 trading days
after deployment — stated plainly rather than worked around.

Same rolling-history-file pattern as nse_data_provider.py's _persist_delivery_history:
data/iv_history.json, json_file_lock + atomic_write_json for the read-modify-write cycle,
keep the last 20 entries per symbol.
"""

import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

from json_utils import atomic_write_json, read_json, json_file_lock
from env_utils import DATA_DIR

logger = logging.getLogger("IVHistoryTracker")

IV_HISTORY_FILE = os.path.join(DATA_DIR, "iv_history.json")
REQUIRED_HISTORY_DAYS = 20
LOWER_PERCENTILE_THRESHOLD = 10.0  # spec: "lower 10th percentile"


def record_daily_iv(symbol: str, atm_iv: float) -> None:
    """Idempotent per (symbol, calendar day) — repeated calls on the same day are no-ops, so
    this is safe to call from every scan tick without inflating the history with intraday
    duplicates."""
    if atm_iv is None or atm_iv <= 0:
        return  # unverified IV (NSE's own 0-means-no-recent-trade convention) — don't record it

    today_str = date.today().isoformat()
    with json_file_lock(IV_HISTORY_FILE):
        store: Dict[str, List[Dict[str, Any]]] = read_json(IV_HISTORY_FILE, default={})
        history = store.setdefault(symbol, [])
        if any(e["date"] == today_str for e in history):
            return
        history.append({"date": today_str, "iv": round(float(atm_iv), 2)})
        history.sort(key=lambda e: e["date"])
        store[symbol] = history[-REQUIRED_HISTORY_DAYS:]
        atomic_write_json(IV_HISTORY_FILE, store)


def has_recorded_iv_today(symbol: str) -> bool:
    """Cheap local check so callers can skip an expensive live chain fetch for symbols that
    already have today's IV snapshot recorded — used by the Strategy Engine to throttle
    full-chain fetches to roughly once per symbol per day instead of every scan tick."""
    today_str = date.today().isoformat()
    store: Dict[str, List[Dict[str, Any]]] = read_json(IV_HISTORY_FILE, default={})
    return any(e["date"] == today_str for e in store.get(symbol, []))


def get_iv_percentile(symbol: str, current_iv: float) -> Optional[float]:
    """Percentile rank (0-100) of current_iv within the trailing REQUIRED_HISTORY_DAYS days
    of recorded IV. Returns None if fewer than REQUIRED_HISTORY_DAYS real days exist yet."""
    if current_iv is None or current_iv <= 0:
        return None

    store: Dict[str, List[Dict[str, Any]]] = read_json(IV_HISTORY_FILE, default={})
    history = store.get(symbol, [])
    if len(history) < REQUIRED_HISTORY_DAYS:
        return None

    values = [e["iv"] for e in history[-REQUIRED_HISTORY_DAYS:]]
    below_or_equal = sum(1 for v in values if v <= current_iv)
    return round((below_or_equal / len(values)) * 100.0, 1)


def is_in_lower_iv_percentile(symbol: str, current_iv: float, threshold: float = LOWER_PERCENTILE_THRESHOLD) -> Optional[bool]:
    """None (FAIL LOUD) if not enough history yet — never silently treated as False, since
    that would look identical to a real, verified 'not in the low percentile' read."""
    pct = get_iv_percentile(symbol, current_iv)
    if pct is None:
        return None
    return pct <= threshold
