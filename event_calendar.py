"""
HIGH-IMPACT EVENT CALENDAR — for Strategy F ("Volatility Straddle")
======================================================================
Strategy F needs "a high-impact event (RBI policy, Budget, earnings) scheduled within 48
hours." No event calendar exists anywhere in this codebase. jugaad_data's
NSELive().corporate_announcements() was evaluated as an automatic per-stock results-date
source and rejected empirically: it returns a global, backward-looking feed of the most
recent ~20 disclosures across ALL symbols (already-happened announcement timestamps, not a
per-symbol query, no scheduled-future-date field) — there's no board-meetings/scheduled-
results endpoint exposed by this library. Text-mining a future results date out of the
feed's free-form `attchmntText` prose would be an unreliable guess, not a verified read, so
this module doesn't attempt it.

Source of truth is purely data/event_calendar.json, manually maintained (RBI MPC dates,
Union Budget date, and any per-stock results dates the operator knows about) — same "don't
fabricate, fail loud on missing data" discipline as every other provider here: an event with
no calendar entry is simply not flagged, never guessed.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from json_utils import read_json
from env_utils import DATA_DIR, get_ist_now

logger = logging.getLogger("EventCalendar")

EVENT_CALENDAR_FILE = os.path.join(DATA_DIR, "event_calendar.json")


def _load_events() -> List[Dict[str, Any]]:
    store = read_json(EVENT_CALENDAR_FILE, default={"events": []})
    return store.get("events", [])


def has_high_impact_event_within(asset: str, hours: int = 48, now=None) -> bool:
    """asset: internal asset name (NIFTY50/BANKNIFTY/SENSEX or a bare stock symbol). An event
    entry with scope "ALL" applies to every asset; otherwise scope must match asset exactly
    (case-insensitive, .NS-suffix-agnostic)."""
    now = now or get_ist_now()
    window_end = now + timedelta(hours=hours)
    clean_asset = asset.replace(".NS", "").upper()

    for event in _load_events():
        scope = str(event.get("scope", "ALL")).upper()
        if scope != "ALL" and scope != clean_asset:
            continue
        try:
            event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if now.date() <= event_date <= window_end.date():
            return True

    return False
