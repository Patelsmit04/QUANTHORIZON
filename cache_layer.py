"""
CACHE LAYER — Zero-Latency In-Memory Cache Store
==================================================
Thread-safe, high-performance in-memory cache for live market data.
All API endpoints read from this cache — NEVER from live feeds directly.

Key Namespaces:
    stock:{SYMBOL}:quote   → {ltp, open, high, low, close, prev_close, change_pts, pct_change, volume, ...}
    stock:{SYMBOL}:depth   → {best_bid, best_ask, bid_qty_5l, ask_qty_5l, depth_ratio, ...}
    stock:{SYMBOL}:cvd_1m  → [{minute, buy_vol, sell_vol, net_delta, tick_count}, ...]
    index:{NAME}:quote     → {ltp, prev_close, change_pts, pct_change, ...}
    oc:{INDEX}:chain       → Full option chain JSON
    block_deals:today      → [{symbol, qty, price, value_cr, ...}]
    meta:ws_status         → {connected, last_tick_ts, subscribed_count}
    meta:angel_session     → {logged_in, client_id, token_expiry}
"""

import time
import threading
import logging
from typing import Any, Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger("CacheLayer")


class CacheStore:
    """Thread-safe in-memory key-value cache with optional TTL eviction."""

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._ttl: Dict[str, float] = {}  # key -> expiry_timestamp (0 = no expiry)
        self._lock = threading.RLock()
        logger.info("CacheStore initialized (in-memory dict mode, zero-latency).")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value. Returns default if key missing or expired. O(1)."""
        with self._lock:
            if key not in self._store:
                return default
            # Check TTL
            expiry = self._ttl.get(key, 0)
            if expiry > 0 and time.time() > expiry:
                del self._store[key]
                del self._ttl[key]
                return default
            return self._store[key]

    def set(self, key: str, value: Any, ttl_seconds: int = 0) -> None:
        """Set a value with optional TTL (seconds). ttl=0 means no expiry."""
        with self._lock:
            self._store[key] = value
            if ttl_seconds > 0:
                self._ttl[key] = time.time() + ttl_seconds
            elif key in self._ttl:
                del self._ttl[key]

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if key existed."""
        with self._lock:
            existed = key in self._store
            self._store.pop(key, None)
            self._ttl.pop(key, None)
            return existed

    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None

    def get_all_matching(self, prefix: str) -> Dict[str, Any]:
        """Get all keys matching a prefix. E.g. 'stock:' returns all stock quotes."""
        now = time.time()
        result = {}
        with self._lock:
            for key, value in self._store.items():
                if key.startswith(prefix):
                    expiry = self._ttl.get(key, 0)
                    if expiry > 0 and now > expiry:
                        continue
                    result[key] = value
        return result

    def get_stock_quotes_snapshot(self) -> List[Dict[str, Any]]:
        """Get all stock quotes as a list for /api/live-stocks. Ultra-fast bulk read."""
        now = time.time()
        quotes = []
        with self._lock:
            for key, value in self._store.items():
                if key.startswith("stock:") and key.endswith(":quote"):
                    expiry = self._ttl.get(key, 0)
                    if expiry > 0 and now > expiry:
                        continue
                    if isinstance(value, dict):
                        quotes.append(value)
        return quotes

    def get_index_quotes_snapshot(self) -> List[Dict[str, Any]]:
        """Get all index quotes as a list for /api/indices. Ultra-fast bulk read."""
        now = time.time()
        quotes = []
        with self._lock:
            for key, value in self._store.items():
                if key.startswith("index:") and key.endswith(":quote"):
                    expiry = self._ttl.get(key, 0)
                    if expiry > 0 and now > expiry:
                        continue
                    if isinstance(value, dict):
                        quotes.append(value)
        return quotes

    def set_bulk_stock_quotes(self, quotes_dict: Dict[str, Dict]) -> int:
        """Bulk-write stock quotes from a {symbol: quote_data} dict. Returns count written."""
        with self._lock:
            for symbol, data in quotes_dict.items():
                self._store[f"stock:{symbol}:quote"] = data
            return len(quotes_dict)

    def set_bulk_index_quotes(self, quotes_dict: Dict[str, Dict]) -> int:
        """Bulk-write index quotes from a {name: quote_data} dict. Returns count written."""
        with self._lock:
            for name, data in quotes_dict.items():
                self._store[f"index:{name}:quote"] = data
            return len(quotes_dict)

    def get_stats(self) -> Dict[str, Any]:
        """Cache statistics for health monitoring."""
        now = time.time()
        with self._lock:
            total_keys = len(self._store)
            expired = sum(1 for k, exp in self._ttl.items() if exp > 0 and now > exp)
            stock_quotes = sum(1 for k in self._store if k.startswith("stock:") and k.endswith(":quote"))
            index_quotes = sum(1 for k in self._store if k.startswith("index:") and k.endswith(":quote"))
            cvd_keys = sum(1 for k in self._store if k.endswith(":cvd_1m"))
            depth_keys = sum(1 for k in self._store if k.endswith(":depth"))

        ws_status = self.get("meta:ws_status", {})
        last_tick = ws_status.get("last_tick_ts", 0)
        tick_age = round(now - last_tick, 1) if last_tick > 0 else -1

        return {
            "total_keys": total_keys,
            "expired_keys": expired,
            "stock_quotes": stock_quotes,
            "index_quotes": index_quotes,
            "cvd_buckets": cvd_keys,
            "depth_keys": depth_keys,
            "ws_connected": ws_status.get("connected", False),
            "last_tick_age_sec": tick_age,
        }

    def flush_all(self) -> int:
        """Clear entire cache. Returns count of keys removed."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self._ttl.clear()
            return count

    def flush_prefix(self, prefix: str) -> int:
        """Clear all keys matching a prefix. Returns count removed."""
        with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]
                self._ttl.pop(k, None)
            return len(keys_to_remove)


# ─── Singleton ───────────────────────────────────────────────
cache = CacheStore()
