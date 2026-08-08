"""
Shared .env loading — was implemented independently in app.py and news_provider.py
(Phase-1 audit finding #7), each with the identical "load .env if present, else
.env.example as a placeholder fallback" fallback. One copy here, both callers use it.
"""

import os
from dotenv import load_dotenv


def load_env_with_fallback(base_dir: str) -> None:
    env_file = os.path.join(base_dir, ".env")
    example_file = os.path.join(base_dir, ".env.example")
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True)
    elif os.path.exists(example_file):
        load_dotenv(example_file, override=False)


def _get_data_dir() -> str:
    """
    10 modules each independently hardcoded DATA_DIR = "data" (a path relative to the
    deployment's own directory). That's fine for `python app.py` on a persistent host, but
    on Vercel the deployment bundle is read-only — only /tmp is writable — so every attempt
    to create/open a file under "data/" crashed the app on import (sqlite3.OperationalError:
    unable to open database file), a 500 on every single request. VERCEL=1 is set
    automatically in that runtime; redirect to /tmp there instead of crashing.

    Note /tmp on Vercel is ephemeral per-instance, not persistent across cold starts or
    shared across concurrent instances — this makes the app importable and servable there,
    it does not change the existing, separately-documented fact that the autonomous
    scheduler doesn't run on serverless (see README's deployment note).
    """
    if os.environ.get("VERCEL"):
        return "/tmp/data"
    return "data"


import threading

DATA_DIR = _get_data_dir()

shutdown_event = threading.Event()


def interruptible_sleep(seconds: float) -> bool:
    """
    Sleeps for `seconds` but returns immediately True if shutdown_event is set on Ctrl+C / SIGINT.
    Returns False if the timeout elapsed normally without interruption.
    """
    return shutdown_event.wait(timeout=seconds)


import zoneinfo
from datetime import datetime

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def get_ist_now() -> datetime:
    """Returns current datetime explicitly in Asia/Kolkata (IST) timezone."""
    return datetime.now(IST)


def get_ist_today_str() -> str:
    """Returns current date string (YYYY-MM-DD) explicitly in Asia/Kolkata (IST) timezone."""
    return get_ist_now().strftime("%Y-%m-%d")

