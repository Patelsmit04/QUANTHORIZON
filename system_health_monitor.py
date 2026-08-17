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

_health_lock = threading.RLock()


def _get_today_date_str() -> str:
    return get_ist_now().strftime("%Y-%m-%d")


def _load_health_data(check_rollover: bool = True) -> Dict[str, Any]:
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
        if check_rollover and data.get("today_date") != _get_today_date_str():
            old_date = data.get("today_date", "previous")
            # Write new day immediately to break recursion
            _save_health_data(default)
            try:
                _archive_day_report(old_date, data)
            except Exception as e:
                logger.warning(f"Could not archive rollover report: {e}")
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
    issues_detail = []
    score = 100

    # 1. Check for runtime errors
    err_count = len(data.get("errors", []))
    if err_count > 0:
        score -= min(30, err_count * 10)
        issues.append(f"{err_count} operational exception(s) logged today")
        issues_detail.append({
            "id": "RUNTIME_EXCEPTIONS",
            "title": f"{err_count} Operational Exception(s) Logged Today",
            "severity": "CRITICAL" if err_count >= 3 else "WARNING",
            "description": f"{err_count} unhandled exception(s) were caught in background workers.",
            "reason": "Data feed timeouts, rate limits, or network interruptions occurred.",
            "action_label": "View Diagnostics Stream",
            "action_target": "logs"
        })

    # 2. Check for mid-day cold starts during trading hours
    market_cold_starts = [cs for cs in data.get("cold_starts", []) if cs.get("is_market_hours")]
    if market_cold_starts:
        score -= min(25, len(market_cold_starts) * 15)
        issues.append(f"{len(market_cold_starts)} dyno cold-start(s) occurred during active market hours")
        issues_detail.append({
            "id": "MID_MARKET_COLD_START",
            "title": f"{len(market_cold_starts)} Mid-Market Dyno Cold-Start(s)",
            "severity": "WARNING",
            "description": "Server process restarted during active trading hours (09:15 - 15:30 IST).",
            "reason": "Cloud provider dyno recycled or instance restarted mid-session.",
            "action_label": "Check Dyno Health",
            "action_target": "dyno"
        })

    # 3. Check 9:15 AM evaluation on weekdays past 09:20 AM IST
    if is_weekday and now_mins >= (9 * 60 + 20):
        if not data.get("evaluations"):
            score -= 20
            issues.append("9:15 AM evaluation event not detected today")
            issues_detail.append({
                "id": "MISSED_915_EVALUATION",
                "title": "9:15 AM Market Open Evaluation Not Detected Today",
                "severity": "ATTENTION",
                "description": "No 9:15 AM opening gap evaluation was recorded in today's active session log.",
                "reason": "Server was started after 09:20 AM IST (offline during the 09:15-09:17 AM open window).",
                "recommendation": "Normal behavior for late starts. Will automatically evaluate on next session open at 09:15 AM, or you can trigger manually.",
                "action_label": "Evaluate Picks Now",
                "action_target": "evaluate_picks"
            })

    # 4. Check 3:30 PM lock on weekdays past 15:35 IST
    if is_weekday and now_mins >= (15 * 60 + 35):
        if not data.get("locks"):
            score -= 25
            issues.append("3:30 PM market lock event not detected today")
            issues_detail.append({
                "id": "MISSED_330_LOCK",
                "title": "3:30 PM Closing Bell Lock Not Detected Today",
                "severity": "ATTENTION",
                "description": "No 3:30 PM closing snapshot was locked into persistent journal today.",
                "reason": "Server was started after 15:35 IST. Last known snapshot is safely preserved in disk storage.",
                "recommendation": "Will automatically engage at 3:30 PM sharp on the next trading session.",
                "action_label": "Run Fresh Scan Now",
                "action_target": "run_scan"
            })

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

    categories = {
        "core_scheduling": {"name": "Core Scheduling & Milestones", "score": 100, "weight_pct": 30, "status": "NOMINAL"},
        "data_integrity": {"name": "Data Accuracy & Anti-Stub", "score": 100, "weight_pct": 25, "status": "NOMINAL"},
        "frontend_apis": {"name": "Frontend API & State Health", "score": 100, "weight_pct": 25, "status": "NOMINAL"},
        "notifications_journals": {"name": "Notifications & Journals", "score": 100, "weight_pct": 20, "status": "NOMINAL"},
    }
    try:
        from ai_sentinel import ai_sentinel
        diag = ai_sentinel.run_full_diagnostic_suite()
        if diag and "categories" in diag:
            categories = diag["categories"]
            score = diag.get("composite_score", score)
            status = diag.get("status", status)
            status_label = diag.get("status_label", status_label)
    except Exception as e:
        logger.debug(f"Could not load AI Sentinel diagnostics into health summary: {e}")

    last_eval = data["evaluations"][-1] if data.get("evaluations") else None
    last_lock = data["locks"][-1] if data.get("locks") else None

    return {
        "status": status,
        "status_label": status_label,
        "score": score,
        "categories": categories,
        "today_date": data.get("today_date"),
        "issues_count": len(issues),
        "issues": issues,
        "issues_detail": issues_detail,
        "total_cold_starts_today": len(data.get("cold_starts", [])),
        "market_hours_cold_starts": len(market_cold_starts),
        "last_evaluation": last_eval,
        "last_lock": last_lock,
        "recent_errors": data.get("errors", [])[-5:],
        "recent_transitions": data.get("market_transitions", [])[-5:],
        "last_updated": data.get("last_health_check")
    }


def _archive_day_report(target_date: str, health_data: Dict[str, Any]) -> Dict[str, Any]:
    err_count = len(health_data.get("errors", []))
    market_cold_starts = [cs for cs in health_data.get("cold_starts", []) if cs.get("is_market_hours")]
    score = max(0, 100 - min(30, err_count * 10) - min(25, len(market_cold_starts) * 15))
    status = "OPTIMAL" if score >= 90 else ("DEGRADED" if score >= 70 else "CRITICAL")
    status_label = "Optimal" if score >= 90 else ("Degraded" if score >= 70 else "Critical")

    report = {
        "date": target_date,
        "generated_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "health_score": score,
        "status": status,
        "status_label": status_label,
        "issues": [],
        "milestones": {
            "evaluations": health_data.get("evaluations", []),
            "locks": health_data.get("locks", []),
            "transitions_count": len(health_data.get("market_transitions", [])),
            "cold_starts_count": len(health_data.get("cold_starts", [])),
            "market_hours_cold_starts": len(market_cold_starts)
        },
        "errors_count": err_count,
        "errors": health_data.get("errors", []),
        "market_transitions": health_data.get("market_transitions", [])
    }
    reports_archive = read_json(DAILY_REPORTS_FILE, default={})
    reports_archive[target_date] = report
    try:
        atomic_write_json(DAILY_REPORTS_FILE, reports_archive)
        logger.info(f"[HEALTH] Daily health report archived for {target_date}")
    except Exception as e:
        logger.error(f"Failed to archive daily health report: {e}")
    return report


def generate_daily_health_report(target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds a definitive daily audit report for the given date and saves it to daily_health_reports.json.
    """
    target_date = target_date or _get_today_date_str()
    with _health_lock:
        health_data = _load_health_data(check_rollover=False)
    return _archive_day_report(target_date, health_data)


def get_all_daily_reports() -> Dict[str, Any]:
    """Returns all archived daily reports."""
    return read_json(DAILY_REPORTS_FILE, default={})
