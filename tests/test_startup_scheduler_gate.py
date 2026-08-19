"""
M12 follow-up: FastAPI's startup event still fires on every Vercel cold start — nothing about
serverless skips it. The startup half of app.lifespan() used to start the real scheduler threads
unconditionally, so every cold start spawned a thread that immediately tries a live ~209-stock
scan via yfinance in the background, competing with the actual request for the same instance's
CPU/network. This is what was actually causing /api/scan to hang past its timeout even after
the request-handler-level gate (_can_run_live_scan_inline) was added.

Scheduler startup now lives inline in the `lifespan` async context manager (replacing the
deprecated `@app.on_event("startup")` decorator) rather than a standalone
start_background_scheduler() function — these tests drive its startup half the same way
test_ws_broadcast.py exercises other async code from a plain sync test: asyncio.run() over a
small async driver, entering (and immediately exiting) the context manager.
"""
import asyncio
from unittest.mock import MagicMock

import app as appmod


def _drive_lifespan_startup():
    """Enters app.lifespan(), which runs everything up to `yield`, then exits immediately —
    only the startup half matters for these tests."""
    async def _drive():
        async with appmod.lifespan(appmod.app):
            pass
    asyncio.run(_drive())


def test_scheduler_threads_not_started_under_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    thread_spy = MagicMock()
    monkeypatch.setattr(appmod.threading, "Thread", thread_spy)
    capture_spy = MagicMock()
    monkeypatch.setattr(appmod.ws_broadcast, "capture_event_loop", capture_spy)

    _drive_lifespan_startup()

    thread_spy.assert_not_called()
    capture_spy.assert_not_called()


def test_scheduler_threads_started_on_persistent_host(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    started_threads = []

    class FakeThread:
        def __init__(self, target=None, daemon=None, *args, **kwargs):
            self.target = target
            self.daemon = daemon
            self.kwargs = kwargs
            started_threads.append(self)

        def start(self):
            pass  # don't actually run the real scheduler loop in a test

    monkeypatch.setattr(appmod.threading, "Thread", FakeThread)
    capture_spy = MagicMock()
    monkeypatch.setattr(appmod.ws_broadcast, "capture_event_loop", capture_spy)

    _drive_lifespan_startup()

    assert len(started_threads) >= 5
    capture_spy.assert_called_once()
