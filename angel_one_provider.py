"""
ANGEL ONE SmartAPI PROVIDER — Authentication, Scrip Master & Session Management
=================================================================================
Handles:
  1. Automated SmartAPI login via SmartConnect + pyotp TOTP generation.
  2. On-boot scrip master download & in-memory symbol→token lookup.
  3. Session health checks and auto-reauth on token expiry.
  4. Graceful degradation: if login fails, system falls back to yfinance polling.

Environment Variables (.env):
  ANGEL_API_KEY       — SmartAPI key from https://smartapi.angelbroking.com/
  ANGEL_CLIENT_ID     — Angel One login/client ID (e.g., "S12345678")
  ANGEL_PASSWORD      — Angel One login password
  ANGEL_TOTP_SECRET   — Base32 TOTP secret for automated 2FA
"""

import os
import time
import json
import logging
import threading
from datetime import datetime, date
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from env_utils import DATA_DIR

logger = logging.getLogger("AngelOneProvider")

# ─── Credentials from .env ───────────────────────────────────
ANGEL_API_KEY = os.environ.get("ANGEL_API_KEY", "").strip()
ANGEL_CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID", "").strip()
ANGEL_PASSWORD = os.environ.get("ANGEL_PASSWORD", "").strip()
ANGEL_TOTP_SECRET = os.environ.get("ANGEL_TOTP_SECRET", "").strip()

# ─── Module State ────────────────────────────────────────────
_smart_api = None          # SmartConnect instance
_auth_token = None         # JWT auth token for WebSocket
_feed_token = None         # Feed token for WebSocket
_refresh_token = None      # Refresh token
_login_time = None         # Timestamp of last successful login
_scrip_master: Dict[str, Dict] = {}   # symbol_key → {token, symbol, exchange, ...}
_scrip_by_token: Dict[str, Dict] = {} # token_id → {symbol, exchange, ...}
_lock = threading.Lock()
_logged_in = False

SCRIP_MASTER_CACHE_FILE = os.path.join(DATA_DIR, "angel_scrip_master.json")
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


def is_configured() -> bool:
    """Check if Angel One credentials are present in environment."""
    return bool(ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PASSWORD and ANGEL_TOTP_SECRET)


def angel_login() -> Optional[Any]:
    """
    Full automated SmartAPI login with pyotp TOTP generation.
    Returns SmartConnect instance on success, None on failure.
    Thread-safe — only one login runs at a time.
    """
    global _smart_api, _auth_token, _feed_token, _refresh_token, _login_time, _logged_in

    if not is_configured():
        logger.warning(
            "Angel One SmartAPI credentials not configured. "
            "Set ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET in .env. "
            "Running in yfinance fallback mode."
        )
        return None

    with _lock:
        try:
            from SmartApi import SmartConnect
            import pyotp

            obj = SmartConnect(api_key=ANGEL_API_KEY)

            # Generate TOTP
            totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()

            # Login
            data = obj.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp)

            if data.get("status") is False:
                error_msg = data.get("message", "Unknown login error")
                logger.error(f"Angel One login failed: {error_msg}")
                _logged_in = False
                return None

            _auth_token = data["data"]["jwtToken"]
            _refresh_token = data["data"]["refreshToken"]
            _feed_token = obj.getfeedToken()
            _smart_api = obj
            _login_time = time.time()
            _logged_in = True

            logger.info(
                f"Angel One SmartAPI login successful for client {ANGEL_CLIENT_ID}. "
                f"Feed token acquired."
            )

            # Update cache metadata
            try:
                from cache_layer import cache
                cache.set("meta:angel_session", {
                    "logged_in": True,
                    "client_id": ANGEL_CLIENT_ID,
                    "login_time": datetime.now().isoformat(),
                    "token_type": "jwt",
                })
            except Exception:
                pass

            return obj

        except ImportError as ie:
            logger.error(
                f"SmartApi or pyotp not installed: {ie}. "
                f"Run: pip install smartapi-python pyotp"
            )
            _logged_in = False
            return None
        except Exception as e:
            logger.error(f"Angel One login error: {e}")
            _logged_in = False
            return None


def get_smart_api():
    """Get the authenticated SmartConnect instance. Auto-reauths if expired."""
    global _smart_api, _login_time, _logged_in
    if not _logged_in or _smart_api is None:
        return angel_login()

    # Re-authenticate if token is older than 8 hours
    if _login_time and (time.time() - _login_time) > 8 * 3600:
        logger.info("Angel One token older than 8h — re-authenticating...")
        return angel_login()

    return _smart_api


def get_auth_token() -> Optional[str]:
    """Get JWT auth token for WebSocket connection."""
    if not _auth_token:
        angel_login()
    return _auth_token


def get_feed_token() -> Optional[str]:
    """Get feed token for WebSocket connection."""
    if not _feed_token:
        angel_login()
    return _feed_token


# ─── Scrip Master ────────────────────────────────────────────

def _download_scrip_master() -> Optional[List[Dict]]:
    """Download OpenAPIScripMaster.json from Angel One."""
    import requests
    try:
        logger.info("Downloading Angel One Scrip Master (~15MB)...")
        resp = requests.get(SCRIP_MASTER_URL, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"Scrip Master downloaded: {len(data)} instruments.")
            return data
        else:
            logger.error(f"Scrip Master download failed: HTTP {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"Scrip Master download error: {e}")
        return None


def _load_scrip_master_from_cache() -> Optional[List[Dict]]:
    """Load scrip master from local disk cache if fresh (same day)."""
    try:
        if not os.path.exists(SCRIP_MASTER_CACHE_FILE):
            return None
        mtime = os.path.getmtime(SCRIP_MASTER_CACHE_FILE)
        cache_date = datetime.fromtimestamp(mtime).date()
        if cache_date != date.today():
            logger.info("Scrip Master cache is stale (different day) — will re-download.")
            return None
        with open(SCRIP_MASTER_CACHE_FILE, "r") as f:
            data = json.load(f)
        logger.info(f"Scrip Master loaded from cache: {len(data)} instruments.")
        return data
    except Exception as e:
        logger.warning(f"Scrip Master cache load error: {e}")
        return None


def _save_scrip_master_to_cache(data: List[Dict]):
    """Save scrip master to local disk cache."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SCRIP_MASTER_CACHE_FILE, "w") as f:
            json.dump(data, f)
        logger.info(f"Scrip Master saved to cache: {len(data)} instruments.")
    except Exception as e:
        logger.warning(f"Scrip Master cache save error: {e}")


def load_scrip_master() -> int:
    """
    Load scrip master into memory. Tries disk cache first, then downloads.
    Returns number of instruments loaded.
    """
    global _scrip_master, _scrip_by_token

    # Try disk cache first
    data = _load_scrip_master_from_cache()
    if not data:
        data = _download_scrip_master()
        if data:
            _save_scrip_master_to_cache(data)

    if not data:
        logger.error("Failed to load Scrip Master from any source.")
        return 0

    # Build lookup maps
    new_master = {}
    new_by_token = {}
    for item in data:
        token = str(item.get("token", ""))
        symbol = str(item.get("symbol", "")).strip()
        name = str(item.get("name", "")).strip()
        exchange_seg = str(item.get("exch_seg", "")).strip()
        instrument_type = str(item.get("instrumenttype", "")).strip()

        if not token or not symbol:
            continue

        entry = {
            "token": token,
            "symbol": symbol,
            "name": name,
            "exchange": exchange_seg,
            "instrument_type": instrument_type,
            "lot_size": item.get("lotsize", "1"),
            "tick_size": item.get("tick_size", "0.05"),
        }

        # Primary key: SYMBOL-EXCHANGE (e.g., "RELIANCE-NSE")
        key = f"{symbol}-{exchange_seg}"
        new_master[key] = entry

        # Also index by token for reverse lookup from WebSocket ticks
        new_by_token[token] = entry

    with _lock:
        _scrip_master = new_master
        _scrip_by_token = new_by_token

    logger.info(f"Scrip Master indexed: {len(new_master)} entries, {len(new_by_token)} tokens.")
    return len(new_master)


def get_angel_token(symbol: str, exchange: str = "NSE") -> Optional[str]:
    """
    Look up Angel One's internal token ID for a symbol.
    Accepts: "RELIANCE", "RELIANCE.NS", "RELIANCE-EQ"
    """
    clean_sym = symbol.replace(".NS", "").replace("-EQ", "").upper().strip()
    exchange = exchange.upper().strip()

    # Try exact match first
    key = f"{clean_sym}-{exchange}"
    entry = _scrip_master.get(key)
    if entry:
        return entry["token"]

    # Try with -EQ suffix (common for equities)
    key_eq = f"{clean_sym}-EQ-{exchange}"
    entry = _scrip_master.get(key_eq)
    if entry:
        return entry["token"]

    # Fuzzy search: look for symbol in any exchange
    for k, v in _scrip_master.items():
        if v["symbol"] == clean_sym and v["exchange"] == exchange:
            return v["token"]

    return None


def get_symbol_by_token(token: str) -> Optional[Dict]:
    """Reverse lookup: get symbol info from Angel One token ID."""
    return _scrip_by_token.get(str(token))


def get_fo_stock_tokens(fo_symbols: List[str]) -> List[Tuple[str, str, str]]:
    """
    Build WebSocket subscription list for F&O stocks.
    Returns [(exchange_type, token, symbol), ...] for SmartWebSocketV2.
    exchange_type: "nse_cm" for cash market, "nse_fo" for derivatives
    """
    tokens = []
    for sym in fo_symbols:
        clean_sym = sym.replace(".NS", "").upper().strip()
        token = get_angel_token(clean_sym, "NSE")
        if token:
            tokens.append(("nse_cm", token, clean_sym))
        else:
            # Some symbols have slight naming differences
            logger.debug(f"No Angel One token found for {clean_sym}")
    return tokens


def get_index_tokens() -> List[Tuple[str, str, str]]:
    """
    Get tokens for major indices.
    Angel One index tokens are well-known constants.
    """
    # Angel One well-known index tokens
    INDEX_TOKENS = {
        "NIFTY": ("nse_cm", "99926000", "NIFTY"),
        "BANKNIFTY": ("nse_cm", "99926009", "BANKNIFTY"),
        "FINNIFTY": ("nse_cm", "99926037", "FINNIFTY"),
        "SENSEX": ("bse_cm", "99919000", "SENSEX"),
    }
    return list(INDEX_TOKENS.values())


def check_angel_session() -> Dict[str, Any]:
    """Health check for Angel One session."""
    if not is_configured():
        return {
            "status": "UNCONFIGURED",
            "message": "Angel One credentials not set in .env",
            "logged_in": False,
        }

    if not _logged_in or _smart_api is None:
        return {
            "status": "NOT_LOGGED_IN",
            "message": "Angel One session not active. Will attempt login on next market open.",
            "logged_in": False,
        }

    age_hours = round((time.time() - (_login_time or 0)) / 3600, 1)
    return {
        "status": "ACTIVE",
        "client_id": ANGEL_CLIENT_ID,
        "logged_in": True,
        "session_age_hours": age_hours,
        "feed_token_present": bool(_feed_token),
        "message": f"Active session for {ANGEL_CLIENT_ID} ({age_hours}h old)",
    }
