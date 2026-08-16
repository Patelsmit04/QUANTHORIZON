"""
SYSTEM CONTROL & EMERGENCY KILL SWITCH
==============================================================================
Provides manual override and pause controls during forward testing.
Allows instantly halting background scanning, automated execution, and locking
without corrupting trade history, calibration states, or diagnostic logs.
==============================================================================
"""

import os
import json
import logging
from typing import Dict, Any, Optional

from env_utils import DATA_DIR, get_ist_now
from json_utils import atomic_write_json, read_json

logger = logging.getLogger("SystemControl")

CONTROL_FILE = os.path.join(DATA_DIR, "system_control.json")


def _default_state() -> Dict[str, Any]:
    return {
        "is_paused": False,
        "pause_reason": None,
        "paused_at": None,
        "paused_by": None,
        "last_resumed_at": None,
        "last_resumed_by": None,
        "history": []
    }


def get_system_control_state() -> Dict[str, Any]:
    """Returns the current emergency kill-switch / pause state."""
    return read_json(CONTROL_FILE, default=_default_state())


def is_system_paused() -> bool:
    """Returns True if the system is currently paused via kill switch."""
    state = get_system_control_state()
    return bool(state.get("is_paused", False))


def pause_system(reason: str = "Manual Admin Override", paused_by: str = "Admin") -> Dict[str, Any]:
    """
    Emergency pause: immediately halts background scans, automated execution,
    and locks, keeping all historical data, caches, and logs intact.
    """
    state = get_system_control_state()
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    
    state["is_paused"] = True
    state["pause_reason"] = reason
    state["paused_at"] = now_str
    state["paused_by"] = paused_by
    state.setdefault("history", []).append({
        "action": "PAUSE",
        "timestamp": now_str,
        "by": paused_by,
        "reason": reason
    })
    
    atomic_write_json(CONTROL_FILE, state)
    logger.warning(f"[SYSTEM CONTROL] 🛑 SYSTEM PAUSED by {paused_by}: {reason}")
    return state


def resume_system(resumed_by: str = "Admin") -> Dict[str, Any]:
    """
    Resumes standard background scanner and trade operations.
    """
    state = get_system_control_state()
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    
    state["is_paused"] = False
    state["pause_reason"] = None
    state["last_resumed_at"] = now_str
    state["last_resumed_by"] = resumed_by
    state.setdefault("history", []).append({
        "action": "RESUME",
        "timestamp": now_str,
        "by": resumed_by
    })
    
    atomic_write_json(CONTROL_FILE, state)
    logger.info(f"[SYSTEM CONTROL] ▶️ SYSTEM RESUMED by {resumed_by}")
    return state
