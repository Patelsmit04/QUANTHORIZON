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
    On Vercel, the repository root is read-only and only /tmp is writable.
    Redirect DATA_DIR to /tmp/data and initialize it with bundled seed files
    (last_market_scan.json, strategies.json, trade_history.json, event_calendar.json, etc.)
    so serverless requests always serve the full pre-computed datasets and active strategies.
    """
    if os.environ.get("VERCEL"):
        tmp_dir = "/tmp/data"
        try:
            os.makedirs(tmp_dir, exist_ok=True)
            base_dir = os.path.dirname(os.path.abspath(__file__))
            bundled_data_dir = os.path.join(base_dir, "data")
            if os.path.exists(bundled_data_dir):
                import shutil
                for item in os.listdir(bundled_data_dir):
                    src_file = os.path.join(bundled_data_dir, item)
                    dst_file = os.path.join(tmp_dir, item)
                    if os.path.isfile(src_file) and not os.path.exists(dst_file):
                        try:
                            shutil.copy2(src_file, dst_file)
                        except Exception:
                            pass
        except Exception:
            pass
        return tmp_dir
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
