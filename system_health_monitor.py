"""
SYSTEM HEALTH MONITOR & DAILY AUDIT SAFETY NET
==============================================================================
Provides automated monitoring, milestone tracking, and daily health reports for
full-week forward testing.

Tracks:
1. Market status transitions (PRE_MARKET, OPEN, CLOSING_SEQUENCE, CLOSED, HOLIDAY)
2. 9:15 AM Evaluation results (counts, wins/losses, win-rate calculation)
3. 3:25 PM & 3:30 PM Lock events (counts, locked symbols, timestamp precision)
4. Runtime exceptions and warnings with timestamps
5. Hosting dyno cold-starts during active trading hours (09:15 - 15:30 IST)
6. Automatic end-of-day health summary generation with health score (0-100)
==============================================================================
"""

import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional

from env_utils import DATA_DIR, get_ist_now
from json_utils import atomic_write_json, read_json, json_file_lock

logger = logging.getLogger("SystemHealthMonitor")

HEALTH_LOG_FILE = os.path.join(DATA_DIR, "system_health_log.json")
DAILY_REPORTS_FILE = os.path.join(DATA_DIR, "daily_health_reports.json")

_health_lock = threading.Lock()


def _get_today_date_str() -> str:
    return get_ist_now().strftime("%Y-%m-%d")


def _load_health_data() -> Dict[str, Any]:
    default = {
        "today_date": _get_today_date_str(),
        "cold_starts": [],
        "market_transitions": [],
        "evaluations": [],
        "locks": [],
        "errors": [],
        "warnings": [],
        "last_health_check": None
    }
    if not os.path.exists(HEALTH_LOG_FILE):
        return default
    try:
        data = read_json(HEALTH_LOG_FILE, default=default)
        if data.get("today_date") != _get_today_date_str():
            # Archive previous day's report before rolling over if not yet done
            generate_daily_health_report(data.get("today_date", "previous"))
            data = default
        return data
    except Exception as e:
        logger.error(f"Failed to read health log: {e}")
        return default


def _save_health_data(data: Dict[str, Any]):
    data["today_date"] = _get_today_date_str()
    data["last_health_check"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    try:
        atomic_write_json(HEALTH_LOG_FILE, data)
    except Exception as e:
        logger.error(f"Failed to save health log: {e}")


# ---------------------------------------------------------------------------
# LOGGING HOOKS
# ---------------------------------------------------------------------------

def log_cold_start(details: Optional[Dict[str, Any]] = None):
    """Record a process startup / cold start event."""
    with _health_lock:
        data = _load_health_data()
        now = get_ist_now()
        is_market_hours = (9 * 60 + 15) <= (now.hour * 60 + now.minute) <= (15 * 60 + 30) and now.weekday() < 5
        entry = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S IST"),
            "is_market_hours": is_market_hours,
            "details": details or {}
        }
        data["cold_starts"].append(entry)
        _save_health_data(data)
        logger.info(f"[HEALTH] Cold start logged (Market Hours={is_market_hours})")


def log_market_transition(old_status: str, new_status: str, mode: Optional[str] = None):
    """Record a market state transition."""
    with _health_lock:
        data = _load_health_data()
        entry = {
            "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "from_status": old_status,
            "to_status": new_status,
            "mode": mode or ""
        }
        data["market_transitions"].append(entry)
        _save_health_data(data)
        logger.info(f"[HEALTH] Market Transition: {old_status} -> {new_status}")


def log_evaluation_event(evaluated_count: int, wins: int, losses: int, win_rate_pct: float, details: Optional[Dict[str, Any]] = None):
    """Record a 9:15 AM trade evaluation event."""
    with _health_lock:
        data = _load_health_data()
        entry = {
            "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "evaluated_count": evaluated_count,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate_pct,
            "status": "SUCCESS" if evaluated_count >= 0 else "FAILED",
            "details": details or {}
        }
        data["evaluations"].append(entry)
        _save_health_data(data)
        logger.info(f"[HEALTH] Evaluation Event Logged: {evaluated_count} graded, {wins}W/{losses}L ({win_rate_pct}%)")


def log_lock_event(lock_type: str, locked_count: int, symbols: List[str], details: Optional[Dict[str, Any]] = None):
    """Record a 3:25 PM or 3:30 PM lock event."""
    with _health_lock:
        data = _load_health_data()
        entry = {
            "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "lock_type": lock_type,
            "locked_count": locked_count,
            "symbols": symbols,
            "details": details or {}
        }
        data["locks"].append(entry)
        _save_health_data(data)
        logger.info(f"[HEALTH] Lock Event Logged: {lock_type} with {locked_count} symbols ({symbols})")


def log_system_error(component: str, error_msg: str, trace_summary: Optional[str] = None):
    """Record an operational error/exception."""
    with _health_lock:
        data = _load_health_data()
        entry = {
            "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "component": component,
            "message": str(error_msg),
            "trace": trace_summary or ""
        }
        data["errors"].append(entry)
        if len(data["errors"]) > 100:
            data["errors"] = data["errors"][-100:]
        _save_health_data(data)
        logger.warning(f"[HEALTH] Error Logged for {component}: {error_msg}")


# ---------------------------------------------------------------------------
# HEALTH CALCULATION & DAILY REPORT GENERATION
# ---------------------------------------------------------------------------

def get_system_health_summary() -> Dict[str, Any]:
    """
    Returns high-level health score, status flag, and issues count for the UI dashboard.
    """
    with _health_lock:
        data = _load_health_data()

    now = get_ist_now()
    is_weekday = now.weekday() < 5
    now_mins = now.hour * 60 + now.minute

    issues = []
    score = 100

    # 1. Check for runtime errors
    err_count = len(data.get("errors", []))
    if err_count > 0:
        score -= min(30, err_count * 10)
        issues.append(f"{err_count} operational exception(s) logged today")

    # 2. Check for mid-day cold starts during trading hours
    market_cold_starts = [cs for cs in data.get("cold_starts", []) if cs.get("is_market_hours")]
    if market_cold_starts:
        score -= min(25, len(market_cold_starts) * 15)
        issues.append(f"{len(market_cold_starts)} dyno cold-start(s) occurred during active market hours")

    # 3. Check 9:15 AM evaluation on weekdays past 09:20 AM IST
    if is_weekday and now_mins >= (9 * 60 + 20):
        if not data.get("evaluations"):
            # If past 9:20 AM on a trading day and no evaluation logged
            score -= 20
            issues.append("9:15 AM evaluation event not detected today")

    # 4. Check 3:30 PM lock on weekdays past 15:35 IST
    if is_weekday and now_mins >= (15 * 60 + 35):
        if not data.get("locks"):
            score -= 25
            issues.append("3:30 PM market lock event not detected today")

    score = max(0, min(100, score))

    if score >= 90:
        status = "NOMINAL"
        status_label = "All Systems Nominal"
    elif score >= 60:
        status = "ATTENTION_REQUIRED"
        status_label = f"Attention Required ({len(issues)} Issue{'s' if len(issues) > 1 else ''})"
    else:
        status = "CRITICAL"
        status_label = f"Critical System Degradation ({len(issues)} Issues)"

    last_eval = data["evaluations"][-1] if data.get("evaluations") else None
    last_lock = data["locks"][-1] if data.get("locks") else None

    return {
        "status": status,
        "status_label": status_label,
        "score": score,
        "today_date": data.get("today_date"),
        "issues_count": len(issues),
        "issues": issues,
        "total_cold_starts_today": len(data.get("cold_starts", [])),
        "market_hours_cold_starts": len(market_cold_starts),
        "last_evaluation": last_eval,
        "last_lock": last_lock,
        "recent_errors": data.get("errors", [])[-5:],
        "recent_transitions": data.get("market_transitions", [])[-5:],
        "last_updated": data.get("last_health_check")
    }


def generate_daily_health_report(target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds a definitive daily audit report for the given date and saves it to daily_health_reports.json.
    """
    target_date = target_date or _get_today_date_str()
    summary = get_system_health_summary()
    
    with _health_lock:
        health_data = _load_health_data()

    report = {
        "date": target_date,
        "generated_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "health_score": summary["score"],
        "status": summary["status"],
        "status_label": summary["status_label"],
        "issues": summary["issues"],
        "milestones": {
            "evaluations": health_data.get("evaluations", []),
            "locks": health_data.get("locks", []),
            "transitions_count": len(health_data.get("market_transitions", [])),
            "cold_starts_count": len(health_data.get("cold_starts", [])),
            "market_hours_cold_starts": summary["market_hours_cold_starts"]
        },
        "errors_count": len(health_data.get("errors", [])),
        "errors": health_data.get("errors", []),
        "market_transitions": health_data.get("market_transitions", [])
    }

    # Save to persistent history
    reports_archive = read_json(DAILY_REPORTS_FILE, default={})
    reports_archive[target_date] = report
    try:
        atomic_write_json(DAILY_REPORTS_FILE, reports_archive)
        logger.info(f"[HEALTH] Daily health report archived for {target_date}")
    except Exception as e:
        logger.error(f"Failed to archive daily health report: {e}")

    return report


def get_all_daily_reports() -> Dict[str, Any]:
    """Returns all archived daily reports."""
    return read_json(DAILY_REPORTS_FILE, default={})
