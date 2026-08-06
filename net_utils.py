"""
Shared network-call discipline: retry + externally-enforced timeout for any blocking call
(yfinance, jugaad_data) that doesn't reliably expose its own timeout/retry knobs across
library versions.

Phase-1 audit findings #3/#4/#5: every provider's failure handling was a single try/except
with no timeout and no retry, so one transient blip (common with Yahoo Finance) dropped that
data point for the whole cycle instead of recovering, and a genuine network hang could block
the single background scheduler thread indefinitely.

The timeout is enforced externally via a thread pool rather than trusting each library's own
`timeout=` kwarg (yfinance's support for it has varied across versions) — this works
identically regardless of what the wrapped call supports. Caveat, stated plainly rather than
hidden: `Future.cancel()` cannot stop a thread that has already started running (a Python
stdlib limitation, not something this module can fix), so a call that times out keeps running
in the background until it naturally finishes/errors. The bounded pool size below caps how many
such stuck calls can pile up — this trades "unbounded stuck threads" for "the calling code path
never blocks past its timeout", which is the actual problem worth fixing (a frozen scheduler).
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Optional, TypeVar

logger = logging.getLogger("NetUtils")
T = TypeVar("T")

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 2.0

_MAX_WORKERS = 8

# Bounded worker pool — see module docstring's caveat on timed-out-but-still-running calls.
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="net-call")

# M8 audit fix: ThreadPoolExecutor.submit() always accepts new work into an internal, unbounded
# queue even when every worker is busy — a submission just waits silently behind whatever's
# already queued. Combined with this module's own documented caveat (a timed-out call's thread
# keeps running, since Future.cancel() can't stop it), a handful of genuinely hung calls could
# occupy all workers while unrelated calls kept queuing behind them, each one's wall-clock
# `timeout` largely spent waiting for a free worker rather than actually running — a scheduler
# CAS-close fetch stuck at 3:35 PM could make an unrelated /api/stock/{symbol} request
# time out too, with no way to tell the two apart from the caller's side.
#
# This semaphore holds exactly one permit per real worker slot, released only when the
# submitted call actually finishes (success, error, or eventually returning after a caller gave
# up waiting on it) — not when call_with_retry stops waiting on it. That makes pool saturation
# observable and fails fast instead of silently queuing behind stuck calls.
_worker_slots = threading.BoundedSemaphore(_MAX_WORKERS)


def call_with_retry(
    fn: Callable[[], T],
    *,
    label: str,
    retries: int = DEFAULT_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
) -> Optional[T]:
    """Runs fn() with an externally-enforced timeout, retrying on timeout or exception.
    Returns None (FAIL LOUD, matching this codebase's existing provider convention) if every
    attempt fails — never a partial/fabricated result."""
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 2):  # one initial try, then up to `retries` more
        if not _worker_slots.acquire(timeout=timeout):
            last_error = TimeoutError(
                f"{label}: all {_MAX_WORKERS} worker slots busy (pool saturated by slow/stuck "
                f"calls) — not queued behind them"
            )
            if attempt <= retries:
                logger.warning(f"[{label}] attempt {attempt} failed ({last_error}) — retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            break

        future = _executor.submit(fn)
        future.add_done_callback(lambda _f: _worker_slots.release())
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            last_error = TimeoutError(f"{label} timed out after {timeout}s")
            future.cancel()  # no-op if already running — see module docstring
        except Exception as e:
            last_error = e

        if attempt <= retries:
            logger.warning(f"[{label}] attempt {attempt} failed ({last_error}) — retrying in {backoff}s...")
            time.sleep(backoff)

    logger.warning(f"[{label}] failed after {retries + 1} attempt(s): {last_error}")
    return None
