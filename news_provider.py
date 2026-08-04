"""
NEWS & GLOBAL-EVENTS PROVIDER (CurrentsAPI)
============================================
Per-stock and market-wide news, fetched from CurrentsAPI (currentsapi.services) and reduced to
a transparent, keyword-based red/green flag read — not a black-box "sentiment score". Every
flag raised is traceable to the headline that raised it, consistent with this codebase's
FAIL LOUD philosophy: no fabricated confidence, no silent guessing.

COST DISCIPLINE — READ BEFORE TOUCHING THIS FILE: CurrentsAPI's free tier is ~1000
requests/day with a 60-request burst limit. The News section covers the FULL F&O universe
(~211 stocks), which at 1 API call/stock is ~211 calls per pass. THE APP NEVER CALLS
CURRENTSAPI PER USER REQUEST — a background job (refresh_universe_news_cache) fetches news for
every stock and writes it to disk; every user of the News section reads that same cached file
(get_cached_stock_news / get_all_cached_news), so serving 1 user or 10,000 costs the same API
budget: zero. The refresh itself is capped to MAX_REFRESHES_PER_DAY passes (3 × 211 ≈ 633
calls/day), leaving headroom for market news + retries under the 1000/day ceiling.

RELEVANCE NOTE: plain company-name keyword search returns a lot of noise — "Reliance" alone
matches an unrelated US company. Queries here are deliberately scoped with "India" / "NSE" /
the company name together to cut down false matches; it's a heuristic, not a guarantee.
"""

import os
import time
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

from json_utils import atomic_write_json, read_json

load_dotenv()

logger = logging.getLogger("NewsProvider")

CURRENTS_API_BASE = "https://api.currentsapi.services/v1"
API_KEY = os.environ.get("CURRENTS_API_KEY")

DATA_DIR = "data"
STOCK_NEWS_CACHE_FILE = os.path.join(DATA_DIR, "stock_news_cache.json")
NEWS_REFRESH_LOCK_FILE = os.path.join(DATA_DIR, "news_refresh.lock")
LOCK_STALE_AFTER_SECONDS = 900  # a universe pass takes longer than the fundamentals refresh

MAX_REFRESHES_PER_DAY = 3        # hard budget cap: 3 x ~211 stocks =~ 633 calls/day, well under 1000
MIN_HOURS_BETWEEN_REFRESHES = 3  # spreads the 3 passes across the trading day instead of bursting them

# CurrentsAPI sits behind Cloudflare and blocks requests without a normal browser User-Agent.
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}

RECENCY_HOURS = 72  # ignore headlines older than this

RED_FLAG_KEYWORDS = [
    "fraud", "scam", "probe", "investigation", "raid", "lawsuit", "sued", "downgrade",
    "downgraded", "default", "bankruptcy", "insolvency", "resign", "resignation", "sacked",
    "scandal", "penalty", "fine", "banned", "crash", "plunge", "plunges", "slump", "layoff",
    "layoffs", "strike", "recall", "breach", "delayed", "halted", "suspended", "raided",
    "seized", "collapse", "crisis", "warning",
]

GREEN_FLAG_KEYWORDS = [
    "record profit", "upgrade", "upgraded", "buyback", "wins order", "bags order",
    "expansion", "surge", "surges", "rally", "rallies", "outperform", "beats estimates",
    "beat estimates", "strong earnings", "robust growth", "partnership", "acquisition",
    "raises guidance", "record high", "all-time high", "expands capacity", "profit jumps",
]


def _api_available() -> bool:
    if not API_KEY:
        logger.warning("CURRENTS_API_KEY not set — news features disabled.")
        return False
    return True


def _search(keywords: str, max_results: int = 8) -> Optional[List[Dict[str, Any]]]:
    """Raw CurrentsAPI search call. Returns None on any failure — FAIL LOUD, never fabricated."""
    if not _api_available():
        return None
    try:
        resp = requests.get(
            f"{CURRENTS_API_BASE}/search",
            params={"keywords": keywords, "language": "en", "apiKey": API_KEY},
            headers=REQUEST_HEADERS,
            timeout=15,
        )
        if resp.status_code == 429:
            logger.warning(f"CurrentsAPI rate limited on query '{keywords}'.")
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            logger.warning(f"CurrentsAPI returned non-ok status for '{keywords}': {data.get('status')}")
            return None
        return data.get("news", [])[:max_results]
    except Exception as e:
        logger.warning(f"CurrentsAPI search failed for '{keywords}': {e}")
        return None


def _filter_recent(headlines: List[Dict[str, Any]], hours: int = RECENCY_HOURS) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for h in headlines:
        try:
            pub = datetime.strptime(h["published"], "%Y-%m-%d %H:%M:%S %z")
            if pub >= cutoff:
                recent.append(h)
        except Exception:
            recent.append(h)  # keep it if we can't parse the date rather than silently drop it
    return recent


def fetch_stock_news(symbol: str, company_name: str, max_results: int = 5) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch recent news for one stock. `company_name` should be the readable company name
    (e.g. "Axis Bank"), not the raw ticker — ticker-only search is even noisier than company
    names. Returns None if the API is unavailable/failed (FAIL LOUD), [] if it succeeded but
    found nothing relevant/recent.
    """
    clean_sym = symbol.replace(".NS", "").upper()
    raw = _search(f"{company_name} India NSE", max_results=max_results * 2)
    if raw is None:
        return None
    recent = _filter_recent(raw)
    return recent[:max_results]


def fetch_market_news(max_results: int = 10) -> Optional[List[Dict[str, Any]]]:
    """Broad market/macro news likely to move Indian equities generally (index-level, not
    stock-specific): RBI/Fed policy, crude oil, global markets, India macro data."""
    raw = _search("Nifty Sensex India stock market RBI", max_results=max_results * 2)
    if raw is None:
        return None
    return _filter_recent(raw)[:max_results]


def classify_news_signal(headlines: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Transparent keyword-based read of a headline set — NOT a trained sentiment model. Every
    flag traces back to the specific headline and keyword that raised it, so the depth-analysis
    narrative can show its work instead of asserting an opaque "sentiment score".
    """
    if headlines is None:
        return {"verdict": "UNAVAILABLE", "red_hits": [], "green_hits": [], "headline_count": 0, "lookback_hours": RECENCY_HOURS}

    if len(headlines) == 0:
        return {"verdict": "NO_RECENT_NEWS", "red_hits": [], "green_hits": [], "headline_count": 0, "lookback_hours": RECENCY_HOURS}

    red_hits: List[Dict[str, str]] = []
    green_hits: List[Dict[str, str]] = []

    for h in headlines:
        text = f"{h.get('title', '')} {h.get('description', '')}".lower()
        for kw in RED_FLAG_KEYWORDS:
            if kw in text:
                red_hits.append({"keyword": kw, "headline": h.get("title", "")})
        for kw in GREEN_FLAG_KEYWORDS:
            if kw in text:
                green_hits.append({"keyword": kw, "headline": h.get("title", "")})

    red_count = len(red_hits)
    green_count = len(green_hits)

    if red_count >= 2:
        verdict = "NEGATIVE"
    elif red_count == 1 and green_count == 0:
        verdict = "CAUTION"
    elif green_count > red_count:
        verdict = "POSITIVE"
    else:
        verdict = "NEUTRAL"

    return {
        "verdict": verdict,
        "red_hits": red_hits,
        "green_hits": green_hits,
        "headline_count": len(headlines),
        "lookback_hours": RECENCY_HOURS,
    }


def apply_news_gate(stock: Dict[str, Any], news_classification: Dict[str, Any]) -> Dict[str, Any]:
    """
    Same discipline as the fundamental quality gate: news can only hold conviction back, never
    manufacture it. A glowing headline doesn't upgrade a weak technical setup — a red-flagged
    one can downgrade a strong one.
    """
    verdict = news_classification.get("verdict", "UNAVAILABLE")
    gate_applied = None
    priority_level = stock.get("priority_level")
    conviction_level = stock.get("conviction_level")

    if verdict == "NEGATIVE" and priority_level != "P3_LOW":
        gate_applied = f"Capped {priority_level} -> P3_LOW (news verdict: NEGATIVE)"
        priority_level = "P3_LOW"
        conviction_level = "MODERATE" if conviction_level == "HIGH_CONVICTION" else conviction_level
    elif verdict == "CAUTION" and priority_level == "P1_HIGH":
        gate_applied = "Capped P1_HIGH -> P2_MEDIUM (news verdict: CAUTION)"
        priority_level = "P2_MEDIUM"
        conviction_level = "MODERATE"

    stock["priority_level"] = priority_level
    stock["conviction_level"] = conviction_level
    stock["news_signal"] = {**news_classification, "gate_applied": gate_applied}
    return stock


# =============================================================================
# UNIVERSE-WIDE NEWS CACHE — powers the News section for every F&O stock.
# Fetch-once-serve-many: this is the ONLY place CurrentsAPI gets called for the News section.
# =============================================================================

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_universe_news_meta() -> Dict[str, Any]:
    cache = read_json(STOCK_NEWS_CACHE_FILE, default={})
    return cache.get("_meta", {})


def should_refresh_universe_news() -> bool:
    """
    Budget gate: at most MAX_REFRESHES_PER_DAY passes over the full universe, spaced at least
    MIN_HOURS_BETWEEN_REFRESHES apart. Disk-backed (not an in-memory flag) so it survives
    process restarts correctly — see the identical fundamentals-cache bug this pattern fixed.
    """
    meta = get_universe_news_meta()
    today_str = date.today().isoformat()
    refresh_count = meta.get("refresh_count", 0) if meta.get("date") == today_str else 0
    if refresh_count >= MAX_REFRESHES_PER_DAY:
        return False
    last_ts = meta.get("last_refresh_ts")
    if last_ts is None:
        return True
    hours_since = (time.time() - last_ts) / 3600.0
    return hours_since >= MIN_HOURS_BETWEEN_REFRESHES


# CurrentsAPI's burst limit is 60 requests per ~43s window (observed empirically). Fetching
# 211 stocks with too much concurrency blows through that in seconds and the remainder gets
# rate-limited (this happened in testing — 151/211 stocks failed on the first version of this
# function). Chunking with a cooldown between chunks keeps every batch under the burst ceiling.
BURST_SAFE_CHUNK_SIZE = 40
BURST_COOLDOWN_SECONDS = 45


def refresh_universe_news_cache(symbols_with_names: Dict[str, str], max_workers: int = 4) -> Dict[str, Any]:
    """
    symbols_with_names: {clean_symbol: company_name} for the FULL F&O universe (every stock
    with an option chain — not just today's BTST/STBT picks). One API call per stock, paced in
    burst-safe chunks (see BURST_SAFE_CHUNK_SIZE) — a full 211-stock pass takes a few minutes,
    which is fine for a background job that runs at most 3x/day.

    Guarded by should_refresh_universe_news() at the call site — this function itself only
    guards against concurrent runs (lock file), it doesn't re-check the daily budget, so callers
    must check should_refresh_universe_news() first.
    """
    _ensure_data_dir()
    if os.path.exists(NEWS_REFRESH_LOCK_FILE):
        lock_age = time.time() - os.path.getmtime(NEWS_REFRESH_LOCK_FILE)
        if lock_age < LOCK_STALE_AFTER_SECONDS:
            logger.warning(f"Universe news refresh already in progress elsewhere (lock is {lock_age:.0f}s old) — skipping.")
            return {"fetched": 0, "failed": 0, "skipped": "ALREADY_IN_PROGRESS"}
        logger.warning(f"Stale news refresh lock ({lock_age:.0f}s old) — assuming a crashed run and proceeding.")

    with open(NEWS_REFRESH_LOCK_FILE, "w") as f:
        f.write(str(time.time()))

    try:
        if not _api_available():
            return {"fetched": 0, "failed": 0, "skipped": "NO_API_KEY"}

        cache = read_json(STOCK_NEWS_CACHE_FILE, default={})
        today_str = date.today().isoformat()
        fetched, failed = 0, 0
        t0 = time.time()

        symbol_items = list(symbols_with_names.items())
        num_chunks = (len(symbol_items) + BURST_SAFE_CHUNK_SIZE - 1) // BURST_SAFE_CHUNK_SIZE
        logger.info(
            f"Refreshing universe news cache for {len(symbol_items)} F&O stocks "
            f"({num_chunks} burst-safe chunks of <= {BURST_SAFE_CHUNK_SIZE})..."
        )

        def _fetch_one(sym: str, name: str):
            headlines = fetch_stock_news(f"{sym}.NS", name)
            return sym, headlines, classify_news_signal(headlines)

        for chunk_idx in range(0, len(symbol_items), BURST_SAFE_CHUNK_SIZE):
            chunk = symbol_items[chunk_idx:chunk_idx + BURST_SAFE_CHUNK_SIZE]
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_fetch_one, sym, name): sym for sym, name in chunk}
                for future in as_completed(futures):
                    sym = futures[future]
                    try:
                        sym, headlines, classification = future.result()
                        if headlines is None:
                            failed += 1
                            continue
                        cache[sym] = {
                            "symbol": sym,
                            "company_name": symbols_with_names.get(sym, sym),
                            "headlines": headlines,
                            "classification": classification,
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        }
                        fetched += 1
                    except Exception as e:
                        logger.warning(f"Universe news fetch failed for {sym}: {e}")
                        failed += 1

            # Checkpoint after every chunk — a chunk-interrupting reload doesn't lose prior chunks.
            atomic_write_json(STOCK_NEWS_CACHE_FILE, cache)

            is_last_chunk = (chunk_idx + BURST_SAFE_CHUNK_SIZE) >= len(symbol_items)
            if not is_last_chunk:
                logger.info(f"Chunk done ({fetched} ok / {failed} failed so far) — cooling down {BURST_COOLDOWN_SECONDS}s for the burst limit...")
                time.sleep(BURST_COOLDOWN_SECONDS)

        prior_meta = cache.get("_meta", {})
        prior_count = prior_meta.get("refresh_count", 0) if prior_meta.get("date") == today_str else 0
        cache["_meta"] = {
            "date": today_str,
            "refresh_count": prior_count + 1,
            "last_refresh_ts": time.time(),
            "last_refresh_completed_at": datetime.now(timezone.utc).isoformat(),
            "symbol_count": fetched,
        }
        atomic_write_json(STOCK_NEWS_CACHE_FILE, cache)
        elapsed = round(time.time() - t0, 1)
        logger.info(
            f"Universe news refresh complete: {fetched} fetched, {failed} failed, {elapsed}s "
            f"(pass #{prior_count + 1}/{MAX_REFRESHES_PER_DAY} today)."
        )
        return {"fetched": fetched, "failed": failed, "elapsed_sec": elapsed, "refresh_number_today": prior_count + 1}
    finally:
        try:
            os.remove(NEWS_REFRESH_LOCK_FILE)
        except OSError:
            pass


def get_cached_stock_news(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fast, NO-API-CALL read for one stock. This is what serves the News section — every user
    reads this same cached file; nobody's page view ever triggers a CurrentsAPI request.
    """
    clean_sym = symbol.replace(".NS", "").upper()
    cache = read_json(STOCK_NEWS_CACHE_FILE, default={})
    return cache.get(clean_sym)


def get_all_cached_news() -> Dict[str, Any]:
    """Full cached news set for the News section — one disk read, served to unlimited users."""
    cache = read_json(STOCK_NEWS_CACHE_FILE, default={})
    return {k: v for k, v in cache.items() if k != "_meta"}
