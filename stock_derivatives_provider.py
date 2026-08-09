"""
PER-STOCK LIVE DERIVATIVES PROVIDER (F&O stocks) — for the intraday Strategy Engine
======================================================================================
Two live NSE reads via jugaad_data's NSELive, same FAIL LOUD discipline as
options_chain_provider.py (verified empirically against the real endpoints — see below):

- fetch_stock_option_chain(symbol): full per-strike chain via equities_option_chain() — same
  response shape as index_option_chain() (records.data[]/underlyingValue/expiryDates), used
  on-demand only when a strategy is actually about to fire, to resolve ATM/OTM strike + IV.
  Verified live against RELIANCE: real per-strike OI/change-in-OI/IV/expiry data.

- fetch_stock_futures_snapshot(symbol): lightweight near-month futures quote via
  stock_quote_fno() — the FUTSTK row's real futures Open Interest. Verified live against
  RELIANCE. This is what actually backs "OI_Change_15min" (Strategy D/E): NSE's own
  changeinOpenInterest field is a change-since-previous-close snapshot, not a rolling
  intraday window, so this module keeps its own in-memory rolling buffer (record_oi_snapshot
  called once per engine tick) and diffs against a ~15-minutes-ago reading.

Deliberately uses the lighter stock_quote_fno() call for the frequent per-tick OI sampling
across the ~230-stock F&O universe, reserving the heavier full-chain fetch for the moment a
strategy condition actually fires — this materially reduces the NSE scraping load versus
fetching the full option chain on every tick for every stock.

The in-memory OI window is intentionally NOT persisted to disk — it's intraday-only and
naturally resets each day (there is no legitimate "OI change from 15 minutes ago, three days
ago" concept), unlike iv_history_tracker.py's cross-day IV percentile history.
"""

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from net_utils import call_with_retry
from env_utils import get_ist_now

logger = logging.getLogger("StockDerivativesProvider")

_NSE_LIVE_AVAILABLE = False
try:
    from jugaad_data.nse import NSELive
    _NSE_LIVE_AVAILABLE = True
except ImportError:
    logger.warning("jugaad_data NSELive not available. Run: pip install jugaad-data")

OI_WINDOW_MINUTES = 20  # trim buffer beyond this; 15-min change reads from within it
OI_CHANGE_LOOKBACK_MINUTES = 15

_oi_history: Dict[str, Deque[Tuple[datetime, float]]] = {}
_oi_history_lock = threading.Lock()


def _get_client():
    if not _NSE_LIVE_AVAILABLE:
        return None
    return NSELive()


def fetch_stock_option_chain(symbol: str) -> Optional[Dict[str, Any]]:
    """Full live per-strike option chain for one F&O stock (bare symbol, no .NS suffix).
    Returns None (FAIL LOUD) on any failure or empty/unusable payload — never a fabricated
    chain. Shape matches options_chain_provider.fetch_index_option_chain()'s output exactly,
    so callers (option_strike_utils.py) work identically against either."""
    client = _get_client()
    if client is None:
        return None

    clean_symbol = symbol.replace(".NS", "").upper()
    raw = call_with_retry(lambda: client.equities_option_chain(clean_symbol), label=f"stock option chain [{clean_symbol}]", timeout=15.0)
    records = (raw or {}).get("records", {})
    underlying_value = records.get("underlyingValue")
    raw_rows = records.get("data", [])
    expiry_dates = records.get("expiryDates", [])

    if not underlying_value or not raw_rows:
        logger.debug(f"[{clean_symbol}] Stock option chain came back empty — treating as unverified.")
        return None

    strikes: List[Dict[str, Any]] = []
    for row in raw_rows:
        strike_price = row.get("strikePrice")
        if strike_price is None:
            continue

        def _leg(leg_key: str) -> Optional[Dict[str, Any]]:
            leg = row.get(leg_key)
            if not leg:
                return None
            iv = leg.get("impliedVolatility", 0) or 0
            return {
                "open_interest": leg.get("openInterest", 0) or 0,
                "change_in_oi": leg.get("changeinOpenInterest", 0) or 0,
                "iv": iv,
                "iv_verified": iv > 0,
                "ltp": leg.get("lastPrice", 0) or 0,
                "volume": leg.get("totalTradedVolume", 0) or 0,
                "expiry_date": leg.get("expiryDate"),
            }

        strikes.append({"strike_price": strike_price, "ce": _leg("CE"), "pe": _leg("PE")})

    return {
        "symbol": clean_symbol,
        "underlying_value": float(underlying_value),
        "expiry_dates": expiry_dates,
        "strikes": strikes,
        "fetched_at": datetime.now().isoformat(),
        "verified": True,
    }


def fetch_stock_futures_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    """Lightweight near-month futures read (real OI, not a proxy). Returns None (FAIL LOUD)
    if the fetch fails or no FUTSTK row is present."""
    client = _get_client()
    if client is None:
        return None

    clean_symbol = symbol.replace(".NS", "").upper()
    raw = call_with_retry(lambda: client.stock_quote_fno(clean_symbol), label=f"stock futures [{clean_symbol}]", timeout=15.0)
    rows = (raw or {}).get("data", [])
    fut_row = next((r for r in rows if r.get("instrumentType") == "FUTSTK"), None)
    if fut_row is None:
        return None

    return {
        "symbol": clean_symbol,
        "open_interest": fut_row.get("openInterest", 0) or 0,
        "change_in_oi_since_prev_close": fut_row.get("changeinOpenInterest", 0) or 0,
        "underlying_value": fut_row.get("underlyingValue"),
        "fetched_at": datetime.now().isoformat(),
    }


def record_oi_snapshot(symbol: str, oi_value: float, ts: Optional[datetime] = None) -> None:
    """Appends one (timestamp, oi) reading to symbol's rolling window, trimming anything
    older than OI_WINDOW_MINUTES. Call this once per engine tick per scanned stock."""
    ts = ts or get_ist_now()
    with _oi_history_lock:
        buf = _oi_history.setdefault(symbol, deque())
        buf.append((ts, oi_value))
        cutoff = ts.timestamp() - OI_WINDOW_MINUTES * 60
        while buf and buf[0][0].timestamp() < cutoff:
            buf.popleft()


def get_oi_change_15min(symbol: str, now: Optional[datetime] = None) -> Optional[float]:
    """% change in OI versus the reading closest to (but not more recent than)
    OI_CHANGE_LOOKBACK_MINUTES ago. Returns None (FAIL LOUD) if there's no snapshot old
    enough yet to measure a real 15-minute change from — never estimates off a shorter
    window."""
    now = now or get_ist_now()
    with _oi_history_lock:
        buf = _oi_history.get(symbol)
        if not buf or len(buf) < 2:
            return None

        latest_ts, latest_oi = buf[-1]
        target_ts = now.timestamp() - OI_CHANGE_LOOKBACK_MINUTES * 60

        baseline = None
        for ts, oi in buf:
            if ts.timestamp() <= target_ts:
                baseline = (ts, oi)
            else:
                break

        if baseline is None:
            return None  # oldest reading isn't yet 15 minutes old — not enough history today

        baseline_oi = baseline[1]
        if baseline_oi == 0:
            return None
        return round(((latest_oi - baseline_oi) / baseline_oi) * 100.0, 2)


def reset_oi_history() -> None:
    """Clears the in-memory OI window for all symbols — call once at the start of each
    trading session so a new day never diffs against yesterday's leftover readings."""
    with _oi_history_lock:
        _oi_history.clear()
