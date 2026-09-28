"""
Sentry Error Tracking — Centralized Configuration
===================================================

Single-point initialization for Sentry across the entire QUANTHORIZON/TRADEXO stack.
Import and call ``init_sentry()`` once at startup (before the FastAPI app is created)
to enable:

1. Automatic ASGI middleware that captures unhandled exceptions on every endpoint
2. Performance monitoring (traces) at a configurable sample rate
3. Explicit ``capture_exception()`` / ``capture_message()`` wrappers for silent-failure
   hotspots (lock sequence, evaluation, data providers)

If ``SENTRY_DSN`` is not set in the environment, every function here is a no-op — the app
runs exactly as before with zero overhead.
"""

import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("BTSTScanner")

# ── State ────────────────────────────────────────────────────────────────────
_initialized = False
_enabled = False


def _get_ist_now() -> datetime:
    """Return current time in IST (UTC+5:30)."""
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _before_send(event, hint):
    """
    Pre-send filter to reduce noise on the free tier.

    Drops:
    - ConnectionResetError / BrokenPipeError (normal WebSocket disconnects)
    - yfinance rate-limit 429 warnings (noisy but non-critical)
    - Generic KeyboardInterrupt (dev Ctrl+C)
    """
    if "exc_info" in hint:
        exc_type, exc_value, _ = hint["exc_info"]

        # WebSocket / client disconnect noise
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return None

        # KeyboardInterrupt (dev only)
        if exc_type is KeyboardInterrupt:
            return None

        # yfinance rate-limit (logged elsewhere, not actionable via Sentry)
        exc_msg = str(exc_value).lower()
        if "429" in exc_msg and ("yfinance" in exc_msg or "too many requests" in exc_msg):
            return None

    # Tag every event with IST timestamp for easy correlation with market events
    event.setdefault("tags", {})["ist_time"] = _get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    return event


def init_sentry():
    """
    Initialize Sentry SDK with FastAPI integration.

    Reads from environment:
    - SENTRY_DSN: The project DSN (leave empty to disable)
    - SENTRY_ENVIRONMENT: "production" | "staging" | "development"
    - SENTRY_RELEASE: Version tag (e.g. "quanthorizon@1.0.0")
    - SENTRY_TRACES_SAMPLE_RATE: Float 0.0-1.0 (default 0.1 = 10%)
    """
    global _initialized, _enabled

    if _initialized:
        return _enabled

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("[Sentry] SENTRY_DSN not set — error tracking disabled (zero-cost no-op).")
        _initialized = True
        _enabled = False
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        traces_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(
                    level=logging.WARNING,       # Capture WARNING+ as breadcrumbs
                    event_level=logging.ERROR,    # Send ERROR+ as Sentry events
                ),
            ],
            traces_sample_rate=traces_rate,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            release=os.environ.get("SENTRY_RELEASE", "quanthorizon@1.0.0"),
            send_default_pii=False,
            before_send=_before_send,
            # Attach server name for multi-instance debugging
            server_name=os.environ.get("RENDER_SERVICE_NAME", "quanthorizon-local"),
        )

        _initialized = True
        _enabled = True
        logger.info(f"[Sentry] Initialized — DSN=...{dsn[-12:]}, env={os.environ.get('SENTRY_ENVIRONMENT', 'production')}, traces={traces_rate}")
        return True

    except ImportError:
        logger.warning("[Sentry] sentry-sdk not installed — error tracking disabled.")
        _initialized = True
        _enabled = False
        return False
    except Exception as e:
        logger.warning(f"[Sentry] Initialization failed: {e} — error tracking disabled.")
        _initialized = True
        _enabled = False
        return False


def capture_exception(exc=None, **context):
    """
    Capture an exception to Sentry with optional context tags.

    Usage:
        try:
            risky_operation()
        except Exception as e:
            sentry_config.capture_exception(e, symbol="RELIANCE.NS", sequence="closing_lock")

    If Sentry is not enabled, this is a no-op.
    """
    if not _enabled:
        return

    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_tag(key, str(value))
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass  # Never let Sentry itself break the app


def capture_message(message: str, level: str = "warning", **context):
    """
    Capture a non-exception message to Sentry.

    Usage:
        sentry_config.capture_message(
            "NSE data returned 0 stocks — data quality gate tripped",
            level="warning",
            provider="nse_data_provider"
        )
    """
    if not _enabled:
        return

    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_tag(key, str(value))
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def set_context(key: str, data: dict):
    """
    Set structured context on the current Sentry scope.

    Usage:
        sentry_config.set_context("lock_sequence", {
            "lock_date": "2026-09-19",
            "picks_count": 5,
            "step": "CAS_CLOSE"
        })
    """
    if not _enabled:
        return

    try:
        import sentry_sdk
        sentry_sdk.set_context(key, data)
    except Exception:
        pass


def add_breadcrumb(message: str, category: str = "custom", level: str = "info", data: dict = None):
    """
    Add a breadcrumb (timeline entry) to the current Sentry scope.

    Breadcrumbs show up in the Sentry event detail as a timeline of what happened
    before an error occurred — useful for debugging the lock/evaluate sequence.
    """
    if not _enabled:
        return

    try:
        import sentry_sdk
        sentry_sdk.add_breadcrumb(
            message=message,
            category=category,
            level=level,
            data=data or {},
        )
    except Exception:
        pass
