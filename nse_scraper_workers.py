"""
NSE HYBRID SCRAPER WORKERS — Option Chain & Block Deals
=========================================================
Background workers that fetch data directly from NSE's public API endpoints.
Bypasses jugaad_data for speed and writes to the in-memory cache.

Workers:
  1. Option Chain Worker — every 3 min, fetches NIFTY & BANKNIFTY option chains
  2. Block Deal Worker  — at 2:25 PM & 3:20 PM, fetches institutional block deals

NSE Anti-Bot Strategy:
  - Visit homepage first to acquire Akamai cookies
  - Rotate User-Agent strings
  - Respect rate limits (1 req / 3 min for option chains)
  - Graceful 403/429 backoff
"""

import os
import time
import logging
import threading
import random
from datetime import datetime
from typing import Dict, Any, Optional, List

from env_utils import IST

logger = logging.getLogger("NSEScraperWorkers")

# ─── NSE Session Management ─────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

NSE_BASE_URL = "https://www.nseindia.com"
OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
BLOCK_DEAL_URL = "https://www.nseindia.com/api/block-deal"

_nse_session = None
_nse_session_lock = threading.Lock()
_last_cookie_refresh = 0.0
COOKIE_REFRESH_INTERVAL = 90.0  # Refresh NSE cookies every 90 seconds


def _get_nse_session():
    """Get or create a requests.Session with valid NSE cookies."""
    global _nse_session, _last_cookie_refresh
    import requests

    with _nse_session_lock:
        now = time.time()
        need_refresh = (
            _nse_session is None or
            (now - _last_cookie_refresh) > COOKIE_REFRESH_INTERVAL
        )

        if need_refresh:
            session = requests.Session()
            ua = random.choice(_USER_AGENTS)
            session.headers.update({
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Referer": "https://www.nseindia.com/",
            })

            try:
                # Visit homepage to acquire cookies
                resp = session.get(NSE_BASE_URL, timeout=10)
                if resp.status_code == 200:
                    _nse_session = session
                    _last_cookie_refresh = now
                    logger.debug(f"NSE session refreshed with UA: {ua[:40]}...")
                else:
                    logger.warning(f"NSE homepage returned {resp.status_code}")
                    if _nse_session is None:
                        _nse_session = session  # Use anyway
            except Exception as e:
                logger.warning(f"NSE session refresh error: {e}")
                if _nse_session is None:
                    _nse_session = session

        return _nse_session


def _nse_get(url: str, timeout: int = 12) -> Optional[Dict]:
    """Make a GET request to NSE with proper session/cookies. Returns parsed JSON or None."""
    session = _get_nse_session()
    if not session:
        return None

    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code in (403, 429):
            logger.warning(f"NSE rate limit/block ({resp.status_code}) for {url}. Refreshing session...")
            global _last_cookie_refresh
            _last_cookie_refresh = 0  # Force cookie refresh
            return None
        else:
            logger.warning(f"NSE request failed: {url} → HTTP {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"NSE request error for {url}: {e}")
        return None


# ─── Option Chain Worker ─────────────────────────────────────

def _parse_option_chain(raw: Dict, index_name: str) -> Optional[Dict]:
    """Parse NSE option chain response into our normalized format."""
    records = raw.get("records", {})
    underlying_value = records.get("underlyingValue")
    raw_rows = records.get("data", [])
    expiry_dates = records.get("expiryDates", [])

    if underlying_value is None or not raw_rows:
        return None

    strikes = []
    for row in raw_rows:
        strike_price = row.get("strikePrice")
        if strike_price is None:
            continue

        def _leg(leg_key: str) -> Optional[Dict]:
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

        strikes.append({
            "strike_price": strike_price,
            "ce": _leg("CE"),
            "pe": _leg("PE"),
        })

    return {
        "index_name": index_name,
        "nse_symbol": index_name,
        "underlying_value": float(underlying_value),
        "expiry_dates": expiry_dates,
        "strikes": strikes,
        "fetched_at": datetime.now().isoformat(),
        "verified": True,
        "source": "NSE_DIRECT_SCRAPER",
    }


def _fetch_option_chain(symbol: str) -> Optional[Dict]:
    """Fetch and parse option chain for one index symbol."""
    url = OPTION_CHAIN_URL.format(symbol=symbol)
    raw = _nse_get(url)
    if raw:
        return _parse_option_chain(raw, symbol)
    return None


def run_option_chain_worker(stop_event: threading.Event):
    """
    Background worker: fetches NIFTY & BANKNIFTY option chains every 3 minutes.
    Writes to cache for zero-latency API responses.
    Falls back to jugaad_data on scrape failure.
    """
    from cache_layer import cache
    logger.info("NSE Option Chain Worker started (3-min cycle).")

    INDICES = ["NIFTY", "BANKNIFTY"]
    INTERVAL = 180  # 3 minutes

    while not stop_event.is_set():
        try:
            now = datetime.now(IST)
            # Only run during market-ish hours (09:00 - 16:00)
            if now.weekday() < 5 and 9 <= now.hour <= 15:
                for idx in INDICES:
                    chain = _fetch_option_chain(idx)
                    if chain and chain.get("strikes"):
                        cache.set(f"oc:{idx}:chain", chain, ttl_seconds=300)  # 5 min TTL
                        logger.info(
                            f"Option chain cached: {idx} "
                            f"({len(chain['strikes'])} strikes, "
                            f"spot={chain['underlying_value']})"
                        )
                    else:
                        # Fallback to jugaad_data
                        try:
                            from options_chain_provider import fetch_index_option_chain
                            mapped = {"NIFTY": "NIFTY50", "BANKNIFTY": "BANKNIFTY"}
                            fallback = fetch_index_option_chain(mapped.get(idx, idx))
                            if fallback:
                                fallback["source"] = "JUGAAD_DATA_FALLBACK"
                                cache.set(f"oc:{idx}:chain", fallback, ttl_seconds=300)
                                logger.info(f"Option chain cached via jugaad_data fallback: {idx}")
                        except Exception as fb_err:
                            logger.warning(f"jugaad_data option chain fallback failed for {idx}: {fb_err}")

                    time.sleep(2)  # Small delay between indices

        except Exception as e:
            logger.error(f"Option Chain Worker error: {e}")

        # Wait for next cycle
        for _ in range(INTERVAL):
            if stop_event.is_set():
                break
            time.sleep(1)

    logger.info("NSE Option Chain Worker stopped.")


# ─── Block Deal Worker ───────────────────────────────────────

def _fetch_block_deals() -> Optional[List[Dict]]:
    """Fetch today's block deals from NSE."""
    raw = _nse_get(BLOCK_DEAL_URL)
    if not raw:
        return None

    deals = raw.get("data", [])
    if not deals:
        return None

    parsed = []
    min_value_cr = float(os.environ.get("INSTITUTIONAL_FLOW_MIN_VALUE_CR", "25"))

    for deal in deals:
        try:
            symbol = deal.get("BD_SYMBOL", "").strip()
            qty = int(deal.get("BD_QTY_TRD", 0) or 0)
            price = float(deal.get("BD_TP", 0) or 0)
            value = qty * price
            value_cr = round(value / 1e7, 2)  # Convert to crores

            if value_cr >= min_value_cr:
                parsed.append({
                    "symbol": symbol,
                    "client_name": deal.get("BD_CLIENT_NAME", ""),
                    "buy_sell": deal.get("BD_BUY_SELL", ""),
                    "quantity": qty,
                    "price": price,
                    "value_cr": value_cr,
                    "deal_date": deal.get("BD_DT_DATE", ""),
                    "remark": deal.get("BD_REMARKS", ""),
                })
        except (ValueError, TypeError):
            continue

    return parsed if parsed else None


def run_block_deal_worker(stop_event: threading.Event):
    """
    Background worker: fetches block deals at 2:25 PM and 3:20 PM IST.
    Filters deals >= ₹25 Crore and caches for frontend display.
    """
    from cache_layer import cache
    logger.info("NSE Block Deal Worker started (2:25 PM + 3:20 PM IST).")

    TRIGGER_TIMES = [
        (14, 25),  # 2:25 PM IST
        (15, 20),  # 3:20 PM IST
    ]

    last_fetch_date = {}  # (hour, minute) → date string

    while not stop_event.is_set():
        try:
            now = datetime.now(IST)

            if now.weekday() < 5:  # Weekdays only
                for trigger_hour, trigger_min in TRIGGER_TIMES:
                    trigger_key = (trigger_hour, trigger_min)
                    today_str = now.strftime("%Y-%m-%d")

                    # Check if we're within the trigger window (±2 min)
                    current_mins = now.hour * 60 + now.minute
                    trigger_mins = trigger_hour * 60 + trigger_min

                    if (
                        abs(current_mins - trigger_mins) <= 2 and
                        last_fetch_date.get(trigger_key) != today_str
                    ):
                        logger.info(f"Block Deal Worker triggered at {now.strftime('%H:%M')} IST")
                        deals = _fetch_block_deals()
                        if deals:
                            # Merge with existing cached deals
                            existing = cache.get("block_deals:today", [])
                            existing_symbols = {
                                (d["symbol"], d.get("client_name", ""))
                                for d in existing
                            }
                            for deal in deals:
                                key = (deal["symbol"], deal.get("client_name", ""))
                                if key not in existing_symbols:
                                    existing.append(deal)

                            cache.set("block_deals:today", existing)
                            logger.info(
                                f"Block deals cached: {len(existing)} deals "
                                f"(₹{sum(d['value_cr'] for d in existing):.0f} Cr total)"
                            )
                        else:
                            logger.info("No qualifying block deals found at this checkpoint.")

                        last_fetch_date[trigger_key] = today_str

        except Exception as e:
            logger.error(f"Block Deal Worker error: {e}")

        # Check every 30 seconds
        for _ in range(30):
            if stop_event.is_set():
                break
            time.sleep(1)

    logger.info("NSE Block Deal Worker stopped.")
