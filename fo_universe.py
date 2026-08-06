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
from typing import Set, List

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
    Returns True if symbol is in the authoritative NSE F&O Whitelist.
    Accepts symbols with or without '.NS' suffix (e.g. 'RELIANCE.NS' or 'RELIANCE').
    """
    check_stale_whitelist()
    clean_sym = symbol.replace(".NS", "").upper()
    return clean_sym in NSE_FO_STOCKS


def get_canonical_fo_tickers() -> List[str]:
    """Returns sorted list of all valid NSE F&O tickers in Yahoo Finance format (with .NS)."""
    return sorted([f"{sym}.NS" for sym in NSE_FO_STOCKS])
