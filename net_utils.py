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
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Optional, TypeVar

logger = logging.getLogger("NetUtils")
T = TypeVar("T")

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 2.0

# Bounded worker pool — see module docstring's caveat on timed-out-but-still-running calls.
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="net-call")


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
        future = _executor.submit(fn)
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
