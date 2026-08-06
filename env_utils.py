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


def get_runtime_data_dir() -> str:
    """Runtime-writable storage path, defaulting to /tmp on Vercel serverless."""
    configured = os.environ.get("QUANTHORIZON_DATA_DIR", "").strip()
    if configured:
        return configured
    if os.environ.get("VERCEL") == "1":
        return "/tmp/quanthorizon-data"
    return "data"
