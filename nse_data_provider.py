"""
NSE LIVE DATA PROVIDER — OI & Delivery % Per-Stock History (V3 — jugaad_data)
==============================================================================
Uses jugaad_data library for reliable NSE data access (bypasses 403/Cloudflare).

1. Daily Stock Data with Delivery % — jugaad_data.nse.stock_df()
2. Rolling 10-session per-stock history stored in data/nse_delivery_history.json
   and data/nse_oi_history.json

OI NOTE: jugaad_data's historical stock endpoint doesn't include per-strike OI.
For Futures OI, we compute a proxy: day-over-day Volume change as an OI-direction
indicator, combined with Close vs VWAP. When the user wires in a proper Futures OI
feed (e.g., from a broker API or paid NSE data vendor), they can pass oi_data
directly to evaluate_5_pillar_matrix().
"""

import os
import time
import logging
import warnings
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List

import pandas as pd

from json_utils import atomic_write_json, read_json

# Suppress jugaad_data numpy datetime warnings
warnings.filterwarnings("ignore", category=UserWarning, module="jugaad_data")

logger = logging.getLogger("NSEDataProvider")

DATA_DIR = "data"
OI_HISTORY_FILE = os.path.join(DATA_DIR, "nse_oi_history.json")
DELIVERY_HISTORY_FILE = os.path.join(DATA_DIR, "nse_delivery_history.json")

# Track if jugaad_data is available
_JUGAAD_AVAILABLE = False
try:
    from jugaad_data.nse import stock_df as nse_stock_df
    _JUGAAD_AVAILABLE = True
    logger.info("jugaad_data library loaded successfully.")
except ImportError:
    logger.warning("jugaad_data not installed. Run: pip install jugaad-data")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


_STORE_CACHE: Dict[str, Any] = {}
_STORE_MTIME: Dict[str, float] = {}


def _load_json_store(filepath: str) -> Dict[str, Any]:
    try:
        mtime = os.path.getmtime(filepath) if os.path.exists(filepath) else 0.0
        if filepath in _STORE_CACHE and _STORE_MTIME.get(filepath) == mtime:
            return _STORE_CACHE[filepath]
        data = read_json(filepath, default={})
        _STORE_CACHE[filepath] = data
        _STORE_MTIME[filepath] = mtime
        return data
    except Exception:
        return read_json(filepath, default={})


def _save_json_store(filepath: str, data: Dict[str, Any]):
    _ensure_data_dir()
    atomic_write_json(filepath, data)
    _STORE_CACHE[filepath] = data
    if os.path.exists(filepath):
        _STORE_MTIME[filepath] = os.path.getmtime(filepath)


# =========================================================================
# 1. DELIVERY % FETCHER (Per-Stock, EOD — via jugaad_data)
# =========================================================================

def fetch_stock_delivery_history(symbol: str, lookback_days: int = 20) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch last N sessions of delivery data from NSE via jugaad_data.
    Returns list of {date, delivery_pct, volume, close, vwap} or None on failure.
    """
    if not _JUGAAD_AVAILABLE:
        logger.warning(f"jugaad_data not available. Cannot fetch delivery for {symbol}.")
        return None

    to_date = date.today()
    from_date = to_date - timedelta(days=lookback_days + 10)

    try:
        df = nse_stock_df(symbol, from_date=from_date, to_date=to_date, series="EQ")

        if df is None or df.empty:
            logger.warning(f"No historical data returned for {symbol}")
            return None

        records = []
        for _, row in df.iterrows():
            dt = row.get("DATE", "")
            dt_str = str(dt)[:10] if dt else ""
            delivery_pct = float(row.get("DELIVERY %", 0.0))
            volume = int(row.get("VOLUME", 0))
            close = float(row.get("CLOSE", 0.0))
            vwap = float(row.get("VWAP", 0.0))

            records.append({
                "date": dt_str,
                "delivery_pct": round(delivery_pct, 2),
                "volume": volume,
                "close": round(close, 2),
                "vwap": round(vwap, 2)
            })

        # Sort by date ascending
        records.sort(key=lambda r: r["date"])
        return records if records else None

    except Exception as e:
        logger.error(f"Error fetching delivery history for {symbol}: {e}")
        return None


def _persist_delivery_history(symbol: str, records: List[Dict[str, Any]]):
    """Persist delivery records to the rolling history file."""
    store = _load_json_store(DELIVERY_HISTORY_FILE)

    if symbol not in store:
        store[symbol] = []

    existing_dates = {entry["date"] for entry in store[symbol]}
    for rec in records:
        if rec["date"] not in existing_dates:
            store[symbol].append(rec)

    # Sort and keep last 15
    store[symbol].sort(key=lambda r: r["date"])
    store[symbol] = store[symbol][-15:]
    _save_json_store(DELIVERY_HISTORY_FILE, store)


def get_per_stock_delivery_data(symbol: str, fetch_online: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get real per-stock delivery data: latest delivery % + trailing 10-day avg.
    Fast local store lookup by default to prevent blocking HTTP scan requests.
    """
    store = _load_json_store(DELIVERY_HISTORY_FILE)
    history = store.get(symbol, [])

    if fetch_online or not history:
        fresh_records = fetch_stock_delivery_history(symbol, lookback_days=20)
        if fresh_records:
            _persist_delivery_history(symbol, fresh_records)
            store = _load_json_store(DELIVERY_HISTORY_FILE)
            history = store.get(symbol, [])

    if not history:
        return None

    past_10 = history[-10:]
    latest_delivery_pct = past_10[-1]["delivery_pct"]
    avg_10d = round(sum(e["delivery_pct"] for e in past_10) / len(past_10), 2)

    return {
        "delivery_pct": latest_delivery_pct,
        "avg_10d_delivery_pct": avg_10d,
        "source": "HISTORY_FILE",
        "history_depth": len(past_10)
    }


# =========================================================================
# 2. OI PROXY (Volume-based) — Per-Stock
# =========================================================================
def get_per_stock_oi_data(symbol: str, fetch_online: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get per-stock OI proxy data based on volume history.
    Fast local store lookup by default to prevent blocking HTTP scan requests.
    """
    store = _load_json_store(OI_HISTORY_FILE)
    history = store.get(symbol, [])

    if fetch_online or not history:
        records = fetch_stock_delivery_history(symbol, lookback_days=20)
    else:
        records = store.get(symbol, [])

    if not records or len(records) < 3:
        if len(history) >= 2:
            past_10 = history[-10:]
            latest_oi_proxy = past_10[-1].get("oi_pct_change", 0.0)
            avg_10d = round(sum(abs(e.get("oi_pct_change", 0.0)) for e in past_10) / len(past_10), 2)
            avg_10d = max(0.01, avg_10d)
            return {
                "oi_pct_change": latest_oi_proxy,
                "avg_10d_oi_pct": avg_10d,
                "source": "VOLUME_PROXY_HISTORY",
                "history_depth": len(past_10)
            }
        return None

    # Compute volume-based OI proxy
    volumes = [r["volume"] for r in records if r["volume"] > 0]
    if len(volumes) < 3:
        return None

    latest_vol = volumes[-1]
    # Baseline EXCLUDES latest_vol itself — averaging today's volume into its own baseline would
    # bias the computed % change toward zero and understate real spikes.
    prior_vols = volumes[:-1]
    baseline_window = prior_vols[-10:]
    avg_10d_vol = sum(baseline_window) / len(baseline_window)

    if avg_10d_vol > 0:
        oi_pct_proxy = round(((latest_vol - avg_10d_vol) / avg_10d_vol) * 100.0, 2)
    else:
        oi_pct_proxy = 0.0

    # Compute trailing 10d avg of abs(daily vol % change) as the baseline
    vol_changes = []
    for i in range(1, min(11, len(volumes))):
        if volumes[i - 1] > 0:
            pct = abs((volumes[i] - volumes[i - 1]) / volumes[i - 1]) * 100.0
            vol_changes.append(pct)

    avg_10d_oi_pct = round(sum(vol_changes) / len(vol_changes), 2) if vol_changes else 10.0
    avg_10d_oi_pct = max(0.01, avg_10d_oi_pct)

    # Persist to history
    store = _load_json_store(OI_HISTORY_FILE)
    today_str = date.today().isoformat()
    if symbol not in store:
        store[symbol] = []
    existing_dates = {e["date"] for e in store[symbol]}
    if today_str not in existing_dates:
        store[symbol].append({
            "date": today_str,
            "total_oi": latest_vol,  # Using volume as proxy
            "total_oi_change": int(latest_vol - avg_10d_vol),
            "oi_pct_change": oi_pct_proxy
        })
    store[symbol] = store[symbol][-15:]
    _save_json_store(OI_HISTORY_FILE, store)

    return {
        "oi_pct_change": oi_pct_proxy,
        "avg_10d_oi_pct": avg_10d_oi_pct,
        "source": "VOLUME_PROXY",
        "history_depth": min(10, len(volumes))
    }


# =========================================================================
# 3. BATCH FETCHER — For Multiple Stocks
# =========================================================================

def fetch_all_nse_data(symbols: List[str], delay: float = 0.0, fetch_online: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Batch-fetch per-stock OI and delivery data for a list of symbols.
    Returns {symbol: {"oi_data": {...} or None, "delivery_data": {...} or None}}
    """
    result = {}
    for sym in symbols:
        clean_sym = sym.replace(".NS", "").upper()
        oi = get_per_stock_oi_data(clean_sym, fetch_online=fetch_online)
        delivery = get_per_stock_delivery_data(clean_sym, fetch_online=fetch_online)
        result[clean_sym] = {"oi_data": oi, "delivery_data": delivery}
        if delay > 0 and fetch_online:
            time.sleep(delay)
    return result
