"""
Daily cap on real, billed Claude API calls from the strategy clarification flow — same
discipline as news_provider.py's CurrentsAPI budget (should_refresh_universe_news /
MAX_REFRESHES_PER_DAY), and the identical mechanism already shipped in the sibling AlgoTrader
project. Disk-backed counter, not in-memory, so it survives process restarts correctly — the
same reasoning as every other "once per day" freshness check in this codebase.

Every strategy create/edit that actually changes its scope/pillars/weight-bar/gates triggers a
real API call with no built-in limit otherwise.
"""

import os
import time
import logging
from datetime import date
from typing import Dict, Any

from json_utils import atomic_write_json, read_json, json_file_lock
from env_utils import DATA_DIR
from pg_utils import USE_POSTGRES, pg_read_json, pg_write_json, pg_key_lock

logger = logging.getLogger("ClarificationBudget")

BUDGET_FILE = os.path.join(DATA_DIR, "clarification_budget.json")

MAX_CLARIFICATIONS_PER_DAY = int(os.environ.get("MAX_CLARIFICATIONS_PER_DAY", "20"))


class ClarificationBudgetExceededError(Exception):
    """Raised when today's clarification-call budget is exhausted — callers should surface
    this exactly like a missing API key, never silently skip clarification and let a strategy
    go active unconfirmed."""
    pass


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load() -> Dict[str, Any]:
    if USE_POSTGRES:
        return pg_read_json("clarification_budget", default={})
    return read_json(BUDGET_FILE, default={})


def _save(data: Dict[str, Any]):
    if USE_POSTGRES:
        pg_write_json("clarification_budget", data)
        return
    _ensure_data_dir()
    atomic_write_json(BUDGET_FILE, data)


def _state_lock():
    return pg_key_lock("clarification_budget") if USE_POSTGRES else json_file_lock(BUDGET_FILE)


def check_and_increment_budget() -> None:
    """Call immediately before making a real Claude API call. Raises
    ClarificationBudgetExceededError if today's cap is already used up; otherwise increments
    the counter and returns normally. The increment happens before the call succeeds/fails —
    a failed call still spent a real API request, so it still counts against the budget.

    M8 audit fix: check-then-increment used to be a classic TOCTOU race — two concurrent
    strategy create/edit requests could both read count=19, both pass the <20 check, and both
    fire a real billed call, with the loser's increment overwriting the winner's. The whole
    read-check-write cycle is now serialized per-process via json_file_lock."""
    today_str = date.today().isoformat()
    with _state_lock():
        data = _load()

        count = data.get("count", 0) if data.get("date") == today_str else 0
        if count >= MAX_CLARIFICATIONS_PER_DAY:
            raise ClarificationBudgetExceededError(
                f"Daily clarification budget ({MAX_CLARIFICATIONS_PER_DAY} calls) reached — "
                f"try again tomorrow, or raise MAX_CLARIFICATIONS_PER_DAY in .env if this limit "
                f"is too low for real usage."
            )

        _save({"date": today_str, "count": count + 1, "last_call_ts": time.time()})


def get_budget_status() -> Dict[str, Any]:
    """Read-only status — lets the UI show remaining budget without spending a call."""
    today_str = date.today().isoformat()
    data = _load()
    count = data.get("count", 0) if data.get("date") == today_str else 0
    return {
        "used_today": count,
        "limit_per_day": MAX_CLARIFICATIONS_PER_DAY,
        "remaining_today": max(0, MAX_CLARIFICATIONS_PER_DAY - count),
    }
