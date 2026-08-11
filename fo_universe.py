"""
CANONICAL NSE F&O UNIVERSE WHITELIST & REVIEW CONFIG
====================================================
Authoritative List of NSE Stocks with Active Option Chains (as of August 4, 2026).

NOTE ON F&O REVIEW CYCLE:
NSE/BSE review and update the F&O stock segment roughly every 6 months.
- Last Updated: August 4, 2026
- Next Scheduled Review Date: October 31, 2026 (~6 Months)

If current date exceeds NEXT_REVIEW_DATE, a logger warning will remind you to refresh this whitelist.

CORPORATE-ACTION CORRECTIONS (verified live against Yahoo Finance + web search, 2026-08-04):
- GMRINFRA   -> GMRAIRPORT  (renamed post non-airport-business demerger, Sep 2024)
- GUJGAS     -> GUJGASLTD   (was always the wrong ticker format for Gujarat Gas Ltd)
- IRTC       -> IRCTC       (typo; the real symbol is IRCTC)
- PEL        -> PIRAMALFIN  (Piramal Enterprises delisted 2025-09-23, succeeded by
                              Piramal Finance Ltd / PIRAMALFIN on merger)
- TATAMOTORS -> TMPV        (Tata Motors demerged 2025-10-01; passenger-vehicle entity,
                              incl. JLR, took over the ticker as TMPV. The commercial-vehicle
                              spin-off, TMLCV, isn't carried here — verify its F&O status
                              independently before adding it.)
- ZOMATO     -> ETERNAL     (company renamed to Eternal Ltd, symbol changed 2025-04-09)
- VISHAL     -> VMM         (Vishal Mega Mart's actual NSE symbol is VMM)
- IBERIA, UNITY, NBVENTURES -> REMOVED (no matching live NSE symbol found; likely bad
  entries from an earlier list revision, not verified corporate actions)
"""

import logging
from datetime import date, datetime
from typing import Set, List, Optional

logger = logging.getLogger("FOUniverse")

LAST_UPDATED = "2026-08-04"
NEXT_REVIEW_DATE = date(2026, 10, 31)  # 6-month stale check

# Authoritative Whitelist of NSE F&O Stock Symbols (base ticker without .NS)
NSE_FO_STOCKS: Set[str] = {
    "360ONE", "AARTIIND", "ABB", "ABCAPITAL", "ABFRL", "ACC", "ADANIENSOL", "ADANIENT",
    "ADANIGREEN", "ADANIPORTS", "ADANIPOWER", "ATGL", "ALKEM", "AMBER", "AMBUJACEM",
    "ANGELONE", "APLAPOLLO", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT",
    "ASTRAL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV",
    "BAJAJHLDNG", "BAJFINANCE", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BDL",
    "BEL", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD",
    "BPCL", "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL", "CGPOWER", "CHOLAFIN",
    "CIPLA", "COALINDIA", "COCHINSHIP", "COFORGE", "CONCOR", "CROMPTON", "CUB",
    "CYIENT", "DALBHARAT", "DEEPAKNTR", "DELHIVERY", "DIVISLAB", "DIXON", "DLF",
    "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", "FORCEMOT",
    "GMRAIRPORT", "GNFC", "GODFRYPHLP", "GOKULAGRO", "GRANULES", "GRASIM",
    "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "HINDZINC", "HONAUT", "HUDCO", "HYUNDAI",
    "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDBI", "IDFCFIRSTB", "IEX",
    "IGL", "INDHOTEL", "INDIACEM", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY",
    "IOC", "IRB", "IRCTC", "IRFC", "ITC", "JINDALSTEL", "JIOFIN", "JKCEMENT",
    "JSWENERGY", "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI", "KOTAKBANK",
    "KPITTECH", "LALPATHLAB", "LICHSGFIN", "LIQUIDBEES", "LT", "LTF", "LTTS",
    "M&M", "M&MFIN", "MANAPPURAM", "MANKIND", "MARICO", "MARUTI", "MAZDOCK",
    "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MOTILALOFS", "MPHASIS",
    "MRF", "MUTHOOTFIN", "NACLIND", "NATIONALUM", "NBCC", "NESTLEIND",
    "NMDC", "NTPC", "NYKAA", "OBEROIRLTY", "OIL", "ONGC", "PAGEIND", "PAYTM",
    "PERSISTENT", "PETRONET", "PFC", "PFIZER", "PIDILITIND", "PIIND", "PIRAMALFIN",
    "POLYCAB", "POWERGRID", "PREMIER", "PVRINOX", "RAIN", "RAMCOCEM", "RBLBANK",
    "RECLTD", "RELIANCE", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SIEMENS",
    "SOLARINDS", "SRF", "SULA", "SUNPHARMA", "SUNDARMFIN", "SUNTV", "SWIGGY",
    "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM", "TATAELXSI", "TMPV",
    "TATAPOWER", "TATASTEEL", "TATATECH", "TCS", "TECHM", "TITAN", "TORNTPHARM",
    "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UNIONBANK",
    "UPL", "VBL", "VEDL", "VGUARD", "VOLTAS", "WAAREEENER", "WIPRO", "YESBANK",
    "ZEEL", "ETERNAL", "NAM-INDIA", "VMM"
}


import os
import requests
from env_utils import DATA_DIR
from json_utils import atomic_write_json, read_json

DYNAMIC_CACHE_FILE = os.path.join(DATA_DIR, "fo_universe_cache.json")
_DYNAMIC_FO_SET: Optional[Set[str]] = None


def get_active_fo_set() -> Set[str]:
    """Returns dynamic NSE F&O universe set if available, falling back to canonical static whitelist."""
    global _DYNAMIC_FO_SET
    if _DYNAMIC_FO_SET is not None:
        return _DYNAMIC_FO_SET
    try:
        if os.path.exists(DYNAMIC_CACHE_FILE):
            data = read_json(DYNAMIC_CACHE_FILE, default={})
            symbols = data.get("symbols")
            if symbols and isinstance(symbols, list) and len(symbols) >= 150:
                _DYNAMIC_FO_SET = set(symbols)
                return _DYNAMIC_FO_SET
    except Exception as e:
        logger.warning(f"Error loading dynamic F&O universe cache: {e}")
    _DYNAMIC_FO_SET = NSE_FO_STOCKS
    return _DYNAMIC_FO_SET


def refresh_fo_universe_from_nse() -> Set[str]:
    """
    Attempts to fetch official NSE F&O security master list / market lot CSV from NSE.
    Caches results locally to data/fo_universe_cache.json.
    """
    global _DYNAMIC_FO_SET
    nse_lots_url = "https://archives.nseindia.com/content/fo/fo_mktlots.csv"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    }
    try:
        resp = requests.get(nse_lots_url, headers=headers, timeout=8)
        if resp.status_code == 200 and len(resp.text) > 100:
            lines = resp.text.splitlines()
            parsed_symbols = set()
            for line in lines[1:]:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and parts[1].isalnum():
                    parsed_symbols.add(parts[1].upper())
            if len(parsed_symbols) >= 150:
                _DYNAMIC_FO_SET = parsed_symbols
                os.makedirs(DATA_DIR, exist_ok=True)
                atomic_write_json(DYNAMIC_CACHE_FILE, {
                    "fetched_at": datetime.now().isoformat(),
                    "total_symbols": len(parsed_symbols),
                    "symbols": sorted(list(parsed_symbols))
                })
                logger.info(f"Refreshed dynamic NSE F&O whitelist: {len(parsed_symbols)} stocks.")
                return _DYNAMIC_FO_SET
    except Exception as e:
        logger.warning(f"Failed to fetch dynamic NSE F&O whitelist: {e}")

    return get_active_fo_set()


def check_stale_whitelist():
    """Check if the F&O whitelist is older than 6 months and print a warning if stale."""
    today = date.today()
    if today > NEXT_REVIEW_DATE:
        logger.warning(
            f"⚠️ STALE F&O WHITELIST WARNING: F&O whitelist was last updated on {LAST_UPDATED}. "
            f"NSE/BSE 6-month review period passed on {NEXT_REVIEW_DATE}. Please re-paste fresh F&O list."
        )


def is_valid_fo_stock(symbol: str) -> bool:
    """
    Returns True if symbol is in the active NSE F&O Whitelist (dynamic set or canonical fallback).
    Accepts symbols with or without '.NS' suffix (e.g. 'RELIANCE.NS' or 'RELIANCE').
    """
    check_stale_whitelist()
    clean_sym = symbol.replace(".NS", "").upper()
    active_set = get_active_fo_set()
    return clean_sym in active_set


def get_canonical_fo_tickers() -> List[str]:
    """Returns sorted list of all valid NSE F&O tickers in Yahoo Finance format (with .NS)."""
    active_set = get_active_fo_set()
    return sorted([f"{sym}.NS" for sym in active_set])
