"""
FUNDAMENTAL QUALITY PROVIDER
============================
Free, no-extra-API-key fundamental data via yfinance's Ticker.info, refreshed once per
day (fundamentals don't move intraday — re-fetching every 5-min scan tick would be both
wasteful and pointless) and cached to disk.

This is a QUALITY GATE, not a timing signal: it does not tell you WHEN to enter a BTST/STBT
trade (the 5-Pillar technical matrix already does that) — it tells you whether the underlying
business looks structurally sound enough to trust an overnight hold on. A stock can pass every
technical pillar and still be a company with collapsing earnings and crushing debt; this module
exists to catch that case rather than blindly trusting price/volume action.

FAIL LOUD: any field yfinance doesn't return is left as None and excluded from the quality
checks rather than defaulted to a value that could fake a pass or fail.
"""

import os
import time
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from json_utils import atomic_write_json, read_json
from lock_utils import file_lock
from net_utils import call_with_retry
from env_utils import DATA_DIR

logger = logging.getLogger("FundamentalProvider")
FUNDAMENTALS_CACHE_FILE = os.path.join(DATA_DIR, "fundamentals_cache.json")

STALE_AFTER_DAYS = 14  # beyond this, treat cached fundamentals as unavailable rather than serve very old data

# Fields pulled from yfinance's Ticker.info, and what they're used for below.
FIELDS_OF_INTEREST = [
    "longName", "shortName",  # readable company name — reused by news_provider.py for search relevance
    "sector", "industry", "marketCap",
    "trailingPE", "forwardPE", "priceToBook",
    "returnOnEquity", "profitMargins",
    "debtToEquity",
    "earningsGrowth", "revenueGrowth", "earningsQuarterlyGrowth",
    "heldPercentInsiders", "heldPercentInstitutions",
]


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_cache() -> Dict[str, Any]:
    return read_json(FUNDAMENTALS_CACHE_FILE, default={})


def _save_cache(cache: Dict[str, Any]):
    _ensure_data_dir()
    atomic_write_json(FUNDAMENTALS_CACHE_FILE, cache)


def compute_fundamental_quality(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate available fundamental fields for red/yellow flags. Only checks fields that are
    actually present (not None) — a missing field is skipped, never assumed to pass or fail.
    """
    red_flags: List[str] = []
    yellow_flags: List[str] = []
    checks_run = 0

    profit_margins = fields.get("profitMargins")
    if profit_margins is not None:
        checks_run += 1
        if profit_margins < 0:
            red_flags.append(f"Negative profit margin ({profit_margins * 100:.1f}%)")

    earnings_growth = fields.get("earningsGrowth")
    revenue_growth = fields.get("revenueGrowth")
    if earnings_growth is not None and revenue_growth is not None:
        checks_run += 1
        if earnings_growth < 0 and revenue_growth < 0:
            red_flags.append(
                f"Both earnings ({earnings_growth * 100:.1f}%) and revenue ({revenue_growth * 100:.1f}%) shrinking"
            )
        elif earnings_growth < -0.15:
            yellow_flags.append(f"Earnings declining sharply ({earnings_growth * 100:.1f}%)")

    debt_to_equity = fields.get("debtToEquity")
    if debt_to_equity is not None:
        checks_run += 1
        if debt_to_equity > 200:
            red_flags.append(f"High leverage (Debt/Equity {debt_to_equity:.0f}%)")
        elif debt_to_equity > 120:
            yellow_flags.append(f"Elevated leverage (Debt/Equity {debt_to_equity:.0f}%)")

    trailing_pe = fields.get("trailingPE")
    if trailing_pe is not None:
        checks_run += 1
        if trailing_pe < 0:
            yellow_flags.append("Negative P/E (no trailing earnings)")
        elif trailing_pe > 100:
            yellow_flags.append(f"Very high P/E ({trailing_pe:.1f}x) — priced for perfection")

    insider_holding = fields.get("heldPercentInsiders")
    if insider_holding is not None:
        checks_run += 1
        if insider_holding < 0.05:
            yellow_flags.append(f"Low promoter/insider holding ({insider_holding * 100:.1f}%)")

    if checks_run == 0:
        verdict = "UNKNOWN"
    elif len(red_flags) >= 2:
        verdict = "WEAK"
    elif len(red_flags) == 1:
        verdict = "CAUTION"
    elif len(yellow_flags) >= 2:
        verdict = "STABLE_WITH_CAUTION"
    else:
        verdict = "STABLE"

    return {
        "verdict": verdict,
        "checks_run": checks_run,
        "checks_possible": 5,
        "red_flags": red_flags,
        "yellow_flags": yellow_flags,
    }


def _fetch_single_stock_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch and extract fields of interest for one symbol. Returns None on total failure
    (after retrying — Phase-1 audit finding #4/#5, this had neither a timeout nor a retry)."""
    info = call_with_retry(lambda: yf.Ticker(symbol).info, label=f"fundamentals [{symbol}]", timeout=15.0)
    if not info or len(info) < 3:
        return None
    fields = {k: info.get(k) for k in FIELDS_OF_INTEREST}
    quality = compute_fundamental_quality(fields)
    return {**fields, "quality": quality}


REFRESH_LOCK_FILE = os.path.join(DATA_DIR, "fundamentals_refresh.lock")
LOCK_STALE_AFTER_SECONDS = 600  # a lock older than this is assumed to be from a crashed/killed run, not a live one


def was_refresh_completed_today() -> bool:
    """
    Disk-backed freshness check — NOT an in-memory flag. An in-memory "did I refresh today"
    flag resets every time the process restarts (e.g. `uvicorn --reload` restarting on every
    file save during development), which was silently causing a full-universe refresh on every
    single reload instead of once/day, hammering Yahoo Finance and racing multiple concurrent
    refreshes against the same cache file. Checking the cache's own persisted metadata survives
    restarts correctly.
    """
    cache = _load_cache()
    return cache.get("_meta", {}).get("last_refresh_completed") == date.today().isoformat()


def refresh_fundamentals_cache(symbols: List[str], max_workers: int = 8) -> Dict[str, Any]:
    """
    Refresh the on-disk fundamentals cache for the given symbols (expects raw tickers, e.g.
    'RELIANCE.NS'). Intended to run once per day, not per-scan — yfinance's .info is a much
    heavier call than the OHLCV downloads used for intraday scanning.

    Guards against concurrent runs (e.g. two processes, or a reload racing a manual call) with
    a simple lock file — without it, two overlapping refreshes both read-modify-write the same
    JSON file and the slower one's partial results silently clobber the faster one's complete ones.
    """
    _ensure_data_dir()
    with file_lock(REFRESH_LOCK_FILE, LOCK_STALE_AFTER_SECONDS, label="Fundamentals refresh") as acquired:
        if not acquired:
            return {"fetched": 0, "failed": 0, "elapsed_sec": 0.0, "skipped": "ALREADY_IN_PROGRESS"}

        today_str = date.today().isoformat()
        cache = _load_cache()
        fetched, failed = 0, 0

        logger.info(f"Refreshing fundamentals cache for {len(symbols)} symbols...")
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_symbol = {pool.submit(_fetch_single_stock_fundamentals, sym): sym for sym in symbols}
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                clean_sym = symbol.replace(".NS", "").upper()
                result = future.result()
                if result is not None:
                    cache[clean_sym] = {**result, "as_of_date": today_str}
                    fetched += 1
                else:
                    failed += 1

        cache["_meta"] = {"last_refresh_completed": today_str, "symbol_count": fetched}
        _save_cache(cache)
        elapsed = round(time.time() - t0, 1)
        logger.info(f"Fundamentals cache refresh complete: {fetched} fetched, {failed} failed, {elapsed}s.")
        return {"fetched": fetched, "failed": failed, "elapsed_sec": elapsed, "as_of_date": today_str}


def load_all_fundamentals() -> Dict[str, Any]:
    """Load the whole cache once — pass the result into get_fundamental_data(cache=...) when
    looking up many symbols in a loop, to avoid re-reading/re-parsing the file per symbol."""
    return _load_cache()


def get_fundamental_data(symbol: str, cache: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Fast local cache lookup (no network) — used by the scoring engine on every scan tick.
    Returns None if never cached. Returns cached data with a "stale" flag if the daily refresh
    job hasn't run recently, rather than silently dropping data that's still mostly valid.

    Pass a pre-loaded cache (via load_all_fundamentals()) when calling this in a loop over many
    symbols, otherwise each call re-reads the cache file from disk.
    """
    clean_sym = symbol.replace(".NS", "").upper()
    if cache is None:
        cache = _load_cache()
    entry = cache.get(clean_sym)
    if entry is None:
        return None

    try:
        as_of = datetime.strptime(entry["as_of_date"], "%Y-%m-%d").date()
        age_days = (date.today() - as_of).days
    except Exception:
        age_days = STALE_AFTER_DAYS + 1

    if age_days > STALE_AFTER_DAYS:
        logger.warning(f"[{clean_sym}] Fundamentals cache is {age_days}d old (>{STALE_AFTER_DAYS}d) — treating as unavailable.")
        return None

    result = dict(entry)
    result["stale"] = age_days > 3
    result["age_days"] = age_days
    return result
