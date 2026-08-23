"""
External, independent health/availability monitor for a QUANTHORIZON/TRADEXO deployment.

Runs ENTIRELY OUTSIDE the monitored service -- invoked once per run by an external scheduler
(see .github/workflows/health-monitor.yml). Deliberately NOT a long-running process and NOT
part of app.py: a service that's asleep or crashed cannot reliably monitor its own health, so
this must live somewhere that stays available independently of whatever it's checking.

What one run does:
    1. GET {MONITOR_URL}/health with a bounded timeout, retrying a few times before the run
       itself is scored as a failure (protects against a single transient blip).
    2. Classifies the outcome (HTTP status family / timeout / DNS / connection-refused / other
       network error) rather than collapsing everything into one generic "failed".
    3. Loads prior state (consecutive-failure count, rolling history, current status) from a
       JSON file, updates it, and writes it back -- state.json is this monitor's only memory
       across runs, since each invocation is otherwise stateless.
    4. Fires a DOWN alert on crossing the configured consecutive-failure threshold, and a
       RECOVERY alert (with computed downtime duration) on the next successful check after a
       DOWN state -- not on every single failure/success, which would be noise.

Exit code is non-zero when the site is currently considered DOWN. health-monitor.yml no longer
propagates that into a failed job/GitHub email (see its comments) now that an external uptime
service is the primary alert channel -- the exit code is kept for anyone running this by hand.
"""

import os
import sys
import json
import logging
import socket
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from alerts import send_alert

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("HealthMonitor")

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("MONITOR_TIMEOUT_SECONDS", "12"))
RETRY_ATTEMPTS = int(os.environ.get("MONITOR_RETRY_ATTEMPTS", "3"))
RETRY_DELAY_SECONDS = float(os.environ.get("MONITOR_RETRY_DELAY_SECONDS", "5"))
CONSECUTIVE_FAILURES_THRESHOLD = int(os.environ.get("MONITOR_FAILURE_THRESHOLD", "3"))
HISTORY_MAX_ENTRIES = int(os.environ.get("MONITOR_HISTORY_MAX_ENTRIES", "500"))
STATE_FILE = os.environ.get("MONITOR_STATE_FILE", "state.json")

SITE_LABEL = os.environ.get("MONITOR_SITE_LABEL", "QUANTHORIZON WEBSITE")


def _resolve_target_url() -> str:
    explicit = os.environ.get("MONITOR_URL", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError("Neither MONITOR_URL nor APP_BASE_URL is set -- nothing to check.")
    return f"{base}/health"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _classify_failure(exc: Optional[BaseException], status_code: Optional[int]) -> str:
    """Turns a raw exception/status into one of the distinct error categories the spec asks
    for, instead of a single generic 'failed'."""
    if status_code is not None:
        if status_code == 429:
            return "HTTP_429_RATE_LIMITED"
        if status_code in (401, 403):
            return f"HTTP_{status_code}_AUTH"
        if status_code == 404:
            return "HTTP_404_NOT_FOUND"
        if status_code in (500, 502, 503, 504):
            return f"HTTP_{status_code}_SERVER_ERROR"
        if 400 <= status_code < 500:
            return f"HTTP_{status_code}_CLIENT_ERROR"
        return f"HTTP_{status_code}"
    if isinstance(exc, requests.exceptions.Timeout):
        return "TIMEOUT"
    if isinstance(exc, requests.exceptions.ConnectionError):
        # requests/urllib3 wrap DNS failures as a ConnectionError whose __cause__ chain
        # bottoms out in socket.gaierror -- unwrap it so DNS failures aren't reported as a
        # generic connection error.
        cause = exc
        seen = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, socket.gaierror):
                return "DNS_ERROR"
            if "Connection refused" in str(cause):
                return "CONNECTION_REFUSED"
            cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
        return "CONNECTION_ERROR"
    if exc is not None:
        return "NETWORK_ERROR"
    return "UNKNOWN_ERROR"


def _check_once(url: str) -> Tuple[bool, Optional[int], float, Optional[str]]:
    """Single HTTP attempt. Returns (success, status_code, response_time_ms, error_category)."""
    start = datetime.now()
    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
        elapsed_ms = (datetime.now() - start).total_seconds() * 1000
        if 200 <= resp.status_code < 300:
            return True, resp.status_code, elapsed_ms, None
        return False, resp.status_code, elapsed_ms, _classify_failure(None, resp.status_code)
    except requests.RequestException as e:
        elapsed_ms = (datetime.now() - start).total_seconds() * 1000
        return False, None, elapsed_ms, _classify_failure(e, None)


def check_with_retry(url: str) -> Dict[str, Any]:
    """Retry-before-down logic (spec section 11): a single transient blip must not flip the
    site to DOWN. Only the LAST attempt's numbers are recorded -- earlier attempts are logged
    but don't pollute the response-time history with retry noise."""
    result = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        success, status_code, elapsed_ms, error = _check_once(url)
        logger.info(
            f"Attempt {attempt}/{RETRY_ATTEMPTS}: "
            f"{'OK' if success else 'FAILED'} "
            f"status={status_code} time={elapsed_ms:.0f}ms error={error}"
        )
        result = {"success": success, "status_code": status_code, "response_time_ms": round(elapsed_ms, 1), "error": error}
        if success:
            return result
        if attempt < RETRY_ATTEMPTS:
            import time
            time.sleep(RETRY_DELAY_SECONDS)
    return result


def _load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not parse existing state file ({e}) -- starting fresh.")
    return {
        "current_status": "UNKNOWN",
        "consecutive_failures": 0,
        "consecutive_successes": 0,
        "last_check": None,
        "last_success": None,
        "last_failure": None,
        "down_since": None,
        "history": [],
    }


def _save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def run() -> int:
    url = _resolve_target_url()
    state = _load_state()

    check = check_with_retry(url)
    now = _now_iso()

    entry = {
        "timestamp": now,
        "success": check["success"],
        "status_code": check["status_code"],
        "response_time_ms": check["response_time_ms"],
        "error": check["error"],
    }
    state["history"].append(entry)
    state["history"] = state["history"][-HISTORY_MAX_ENTRIES:]
    state["last_check"] = now

    was_down = state["current_status"] == "DOWN"

    if check["success"]:
        state["consecutive_failures"] = 0
        state["consecutive_successes"] = state.get("consecutive_successes", 0) + 1
        state["last_success"] = now
        state["current_status"] = "HEALTHY"

        if was_down and state.get("down_since"):
            down_since = datetime.fromisoformat(state["down_since"].replace("Z", "+00:00"))
            downtime_seconds = (datetime.now(timezone.utc) - down_since).total_seconds()
            message = (
                f"\U0001F7E2 {SITE_LABEL} RECOVERED\n\n"
                f"URL: {url}\n"
                f"Response time: {check['response_time_ms']:.0f} ms\n"
                f"Downtime: {_format_duration(downtime_seconds)}"
            )
            logger.info("Recovery detected -- sending recovery alert.")
            sent = send_alert(message)
            state["down_since"] = None
            logger.info(f"Recovery alert sent to: {sent or 'none (no channel configured)'}")
    else:
        state["consecutive_successes"] = 0
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        state["last_failure"] = now

        if state["consecutive_failures"] >= CONSECUTIVE_FAILURES_THRESHOLD:
            if state["current_status"] != "DOWN":
                state["down_since"] = now
                message = (
                    f"\U0001F534 {SITE_LABEL} DOWN\n\n"
                    f"URL: {url}\n"
                    f"Time: {now}\n"
                    f"Status: {check['error'] or check['status_code']}\n"
                    f"Consecutive failures: {state['consecutive_failures']}"
                )
                logger.warning("Consecutive failure threshold reached -- sending DOWN alert.")
                sent = send_alert(message)
                logger.info(f"Down alert sent to: {sent or 'none (no channel configured)'}")
            state["current_status"] = "DOWN"
        else:
            logger.info(
                f"Failure {state['consecutive_failures']}/{CONSECUTIVE_FAILURES_THRESHOLD} "
                f"-- below alert threshold, not yet marking DOWN."
            )

    successes = [h for h in state["history"] if h["success"]]
    total = len(state["history"])
    response_times = [h["response_time_ms"] for h in successes]
    state["stats"] = {
        "uptime_pct": round(100.0 * len(successes) / total, 2) if total else None,
        "avg_response_time_ms": round(sum(response_times) / len(response_times), 1) if response_times else None,
        "min_response_time_ms": round(min(response_times), 1) if response_times else None,
        "max_response_time_ms": round(max(response_times), 1) if response_times else None,
        "total_checks": total,
        "failed_checks": total - len(successes),
    }

    _save_state(state)

    logger.info(
        f"Status={state['current_status']} "
        f"uptime={state['stats']['uptime_pct']}% "
        f"consecutive_failures={state['consecutive_failures']}"
    )

    return 1 if state["current_status"] == "DOWN" else 0


if __name__ == "__main__":
    sys.exit(run())
