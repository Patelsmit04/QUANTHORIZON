"""
M12 follow-up: FastAPI's startup event still fires on every Vercel cold start — nothing about
serverless skips it. start_background_scheduler() used to start the real scheduler threads
unconditionally, so every cold start spawned a thread that immediately tries a live ~209-stock
scan via yfinance in the background, competing with the actual request for the same instance's
CPU/network. This is what was actually causing /api/scan to hang past its timeout even after
the request-handler-level gate (_can_run_live_scan_inline) was added.
"""
from unittest.mock import MagicMock

import app as appmod


def test_scheduler_threads_not_started_under_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    thread_spy = MagicMock()
    monkeypatch.setattr(appmod.threading, "Thread", thread_spy)
    capture_spy = MagicMock()
    monkeypatch.setattr(appmod.ws_broadcast, "capture_event_loop", capture_spy)

    appmod.start_background_scheduler()

    thread_spy.assert_not_called()
    capture_spy.assert_not_called()


def test_scheduler_threads_started_on_persistent_host(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    started_threads = []

    class FakeThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon
            started_threads.append(self)

        def start(self):
            pass  # don't actually run the real scheduler loop in a test

    monkeypatch.setattr(appmod.threading, "Thread", FakeThread)
    capture_spy = MagicMock()
    monkeypatch.setattr(appmod.ws_broadcast, "capture_event_loop", capture_spy)

    appmod.start_background_scheduler()

    assert len(started_threads) == 2
    capture_spy.assert_called_once()
