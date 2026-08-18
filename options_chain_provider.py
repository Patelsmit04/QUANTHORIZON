"""
NSE INDEX OPTION CHAIN PROVIDER
=================================
Live per-strike option chain for NSE-traded index derivatives, via jugaad_data's
NSELive().index_option_chain() — verified empirically against the real NSE endpoint (not
assumed): NIFTY and BANKNIFTY return full, real per-strike OI/IV/LTP/volume data. SENSEX
returns an empty payload (underlyingValue=None, zero strike rows) because Sensex options
trade on the BSE, not NSE, and this is an NSE-only data source.

FAIL LOUD, same discipline as every other provider in this codebase: if the chain can't be
fetched or comes back empty, this returns None — never a fabricated/estimated chain. Callers
(index_derivatives_analyzer.py, options_greeks_analyzer.py) must treat None as "can't verify,
don't proceed" for that index, exactly like a missing OI/fundamentals/news read elsewhere.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from net_utils import call_with_retry

logger = logging.getLogger("OptionsChainProvider")

_NSE_LIVE_AVAILABLE = False
try:
    from jugaad_data.nse import NSELive
    _NSE_LIVE_AVAILABLE = True
except ImportError:
    logger.warning("jugaad_data NSELive not available. Run: pip install jugaad-data")

# Sensex isn't included — BSE-traded, no verified source (see module docstring).
OPTION_CHAIN_INDICES = {"NIFTY50": "NIFTY", "BANKNIFTY": "BANKNIFTY"}


def _get_client():
    if not _NSE_LIVE_AVAILABLE:
        return None
    return NSELive()


def fetch_index_option_chain(index_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch and normalize the live option chain for one index. index_name is our internal name
    (NIFTY50 / BANKNIFTY / SENSEX) — mapped to NSE's own symbol internally.

    Returns None (FAIL LOUD) if: the index has no verified NSE option-chain source (SENSEX),
    the client library isn't installed, the fetch fails, or NSE returns an empty/unusable
    payload. Never returns a partially-fabricated chain.
    """
    nse_symbol = OPTION_CHAIN_INDICES.get(index_name)
    if nse_symbol is None:
        logger.warning(f"[{index_name}] No verified NSE option-chain source for this index — skipping (not faking data).")
        return None

    # Cache-first: check fast_cache (populated by nse_scraper_workers every 3 min)
    try:
        from cache_layer import cache as fast_cache
        # NSE scraper uses "NIFTY"/"BANKNIFTY" keys; this function uses "NIFTY50"/"BANKNIFTY"
        cache_key = f"oc:{nse_symbol}:chain"
        cached = fast_cache.get(cache_key)
        if cached and isinstance(cached, dict) and cached.get("strikes"):
            logger.debug(f"Option chain served from fast_cache: {index_name}")
            return cached
    except Exception:
        pass

    client = _get_client()
    if client is None:
        return None

    raw = call_with_retry(lambda: client.index_option_chain(nse_symbol), label=f"option chain [{index_name}]", timeout=15.0)
    records = (raw or {}).get("records", {})
    underlying_value = records.get("underlyingValue")
    raw_rows = records.get("data", [])
    expiry_dates = records.get("expiryDates", [])

    if underlying_value is None or not raw_rows:
        logger.warning(f"[{index_name}] Option chain came back empty — treating as unverified.")
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
                # IV of exactly 0 means NSE had no recent trade to price this leg, not a real
                # zero-volatility market — flagged so downstream Greeks math can skip it rather
                # than compute nonsense from a missing value.
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
        "nse_symbol": nse_symbol,
        "underlying_value": float(underlying_value),
        "expiry_dates": expiry_dates,
        "strikes": strikes,
        "fetched_at": datetime.now().isoformat(),
        "verified": True,
    }


def get_nearest_expiry_chain(chain: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Filter a fetched chain down to only the nearest expiry — most relevant for an
    overnight/BTST read. Returns None if given None (pass-through FAIL LOUD)."""
    if chain is None or not chain.get("expiry_dates"):
        return chain

    nearest_expiry = chain["expiry_dates"][0]
    filtered_strikes = []
    for s in chain["strikes"]:
        ce_expiry = (s.get("ce") or {}).get("expiry_date")
        pe_expiry = (s.get("pe") or {}).get("expiry_date")
        # NSE's expiryDates list uses "DD-Mon-YYYY" while per-leg expiryDate uses "DD-MM-YYYY" —
        # compare by parsed date rather than string equality across the two formats.
        try:
            nearest_parsed = datetime.strptime(nearest_expiry, "%d-%b-%Y").date()
        except ValueError:
            nearest_parsed = None
        matched = False
        for leg_expiry in (ce_expiry, pe_expiry):
            if not leg_expiry:
                continue
            try:
                leg_parsed = datetime.strptime(leg_expiry, "%d-%m-%Y").date()
                if nearest_parsed and leg_parsed == nearest_parsed:
                    matched = True
            except ValueError:
                continue
        if matched:
            filtered_strikes.append(s)

    return {**chain, "expiry_dates": [nearest_expiry], "strikes": filtered_strikes}
