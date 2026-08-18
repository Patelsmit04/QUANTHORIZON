"""
ANGEL ONE WebSocket 2.0 STREAM PROCESSOR
==========================================
Connects to SmartWebSocketV2 for real-time 1-second LTP + Level 2 depth streaming.
Subscribes to ~210 F&O stocks + major indices.
Writes every tick into the cache_layer for zero-latency API responses.
Feeds the synthetic_cvd_engine for order flow delta computation.

Lifecycle:
  1. Called from app.py lifespan via start()
  2. Connects during market hours (09:10-15:35 IST weekdays)
  3. Auto-reconnects with exponential backoff
  4. Gracefully disconnects after market close
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List

from cache_layer import cache
from env_utils import IST

logger = logging.getLogger("AngelWSStream")

# ─── Constants ───────────────────────────────────────────────
MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 9, 10    # Connect 5 min before open
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 35  # Disconnect 5 min after close
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0

# SmartWebSocketV2 subscription modes
MODE_LTP = 1
MODE_QUOTE = 2
MODE_SNAP_QUOTE = 3


class AngelWebSocketStream:
    """Manages the Angel One SmartWebSocketV2 lifecycle and tick processing."""

    def __init__(self):
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._subscribed_count = 0
        self._reconnect_delay = RECONNECT_BASE_DELAY
        self._last_tick_ts = 0.0
        self._tick_count = 0
        self._token_to_symbol: Dict[str, str] = {}
        self._prev_closes: Dict[str, float] = {}  # symbol → prev_close

    def start(self):
        """Start the WebSocket stream in a background thread."""
        if self._running:
            logger.warning("WebSocket stream already running.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AngelWSStream")
        self._thread.start()
        logger.info("Angel One WebSocket stream thread started.")

    def stop(self):
        """Stop the WebSocket stream gracefully."""
        self._running = False
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
        self._connected = False
        logger.info("Angel One WebSocket stream stopped.")

    def get_status(self) -> Dict[str, Any]:
        """Status for health monitoring."""
        now = time.time()
        tick_age = round(now - self._last_tick_ts, 1) if self._last_tick_ts > 0 else -1
        return {
            "running": self._running,
            "connected": self._connected,
            "subscribed_count": self._subscribed_count,
            "total_ticks_processed": self._tick_count,
            "last_tick_age_sec": tick_age,
            "reconnect_delay": self._reconnect_delay,
        }

    def set_prev_closes(self, prev_closes: Dict[str, float]):
        """Set previous close prices for % change computation."""
        self._prev_closes = prev_closes

    # ─── Internal Loop ───────────────────────────────────────

    def _run_loop(self):
        """Main loop: connect during market hours, disconnect after close, reconnect on failure."""
        while self._running:
            try:
                if not self._is_market_hours():
                    self._update_status(connected=False)
                    time.sleep(30)  # Check every 30s outside market hours
                    continue

                # Attempt connection
                self._connect_and_subscribe()

            except Exception as e:
                logger.error(f"WebSocket loop error: {e}")
                self._connected = False
                self._update_status(connected=False)

                # Exponential backoff
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_MAX_DELAY
                )

    def _is_market_hours(self) -> bool:
        """Check if current IST time is within market hours (weekday 09:10-15:35)."""
        now = datetime.now(IST)
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        t = now.hour * 60 + now.minute
        open_t = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MIN
        close_t = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MIN
        return open_t <= t <= close_t

    def _connect_and_subscribe(self):
        """Connect to SmartWebSocketV2 and subscribe to the stock/index universe."""
        try:
            import angel_one_provider as aop

            # Ensure login
            smart_api = aop.get_smart_api()
            if not smart_api:
                logger.warning("Angel One login failed — cannot connect WebSocket. Retrying...")
                time.sleep(10)
                return

            auth_token = aop.get_auth_token()
            feed_token = aop.get_feed_token()

            if not auth_token or not feed_token:
                logger.warning("Missing auth/feed tokens — cannot connect WebSocket.")
                time.sleep(10)
                return

            # Ensure scrip master is loaded
            if not aop._scrip_master:
                aop.load_scrip_master()

            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            # Build subscription token list
            from fo_universe import get_active_fo_set
            fo_symbols = list(get_active_fo_set())

            stock_tokens = aop.get_fo_stock_tokens(fo_symbols)
            index_tokens = aop.get_index_tokens()

            # Build token → symbol mapping
            self._token_to_symbol.clear()
            for exchange, token, symbol in stock_tokens + index_tokens:
                self._token_to_symbol[token] = symbol

            # Create WebSocket instance
            correlation_id = f"tradexo_{int(time.time())}"
            self._ws = SmartWebSocketV2(
                auth_token, aop.ANGEL_API_KEY, aop.ANGEL_CLIENT_ID,
                feed_token, max_retry_attempt=5
            )

            # Set callbacks
            self._ws.on_data = self._on_data
            self._ws.on_open = lambda wsapp: self._on_open(wsapp, stock_tokens, index_tokens)
            self._ws.on_error = self._on_error
            self._ws.on_close = self._on_close

            logger.info(
                f"Connecting Angel One WebSocket... "
                f"({len(stock_tokens)} stocks + {len(index_tokens)} indices)"
            )

            # This is blocking — runs until disconnect
            self._ws.connect()

        except ImportError as ie:
            logger.error(f"SmartApi package not installed: {ie}")
            time.sleep(60)
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            self._connected = False

    def _on_open(self, wsapp, stock_tokens, index_tokens):
        """Called when WebSocket connection is established."""
        logger.info("Angel One WebSocket connected successfully!")
        self._connected = True
        self._reconnect_delay = RECONNECT_BASE_DELAY  # Reset backoff

        # Subscribe in batches (Angel One limit: ~1000 tokens per subscribe call)
        all_tokens = stock_tokens + index_tokens
        batch_size = 50

        for i in range(0, len(all_tokens), batch_size):
            batch = all_tokens[i:i + batch_size]
            # Format for SmartWebSocketV2: [exchange_type, token]
            token_list = []
            for exchange, token, symbol in batch:
                # Exchange type mapping for SmartWebSocketV2
                if exchange == "nse_cm":
                    ex_type = 1  # NSE
                elif exchange == "bse_cm":
                    ex_type = 3  # BSE
                elif exchange == "nse_fo":
                    ex_type = 2  # NSE F&O
                else:
                    ex_type = 1
                token_list.append({
                    "exchangeType": ex_type,
                    "tokens": [token]
                })

            try:
                self._ws.subscribe(correlation_id=f"batch_{i}", mode=MODE_SNAP_QUOTE, token_list=token_list)
                time.sleep(0.1)  # Small delay between subscription batches
            except Exception as e:
                logger.warning(f"Subscription batch {i} error: {e}")

        self._subscribed_count = len(all_tokens)
        self._update_status(connected=True)
        logger.info(f"Subscribed to {self._subscribed_count} tokens in SnapQuote mode.")

    def _on_data(self, wsapp, message):
        """
        Called on every incoming tick. This is the HOT PATH — must be ultra-fast.
        Parses the tick, writes to cache, feeds CVD engine.
        """
        try:
            if not isinstance(message, dict):
                return

            token = str(message.get("token", ""))
            symbol = self._token_to_symbol.get(token)
            if not symbol:
                return

            # Extract price data from Angel One tick format
            ltp = message.get("last_traded_price", 0)
            if isinstance(ltp, int):
                ltp = ltp / 100.0  # Angel One sends price * 100

            if ltp <= 0:
                return

            open_price = (message.get("open_price_of_the_day", 0) or 0) / 100.0
            high = (message.get("high_price_of_the_day", 0) or 0) / 100.0
            low = (message.get("low_price_of_the_day", 0) or 0) / 100.0
            close = (message.get("closed_price", 0) or 0) / 100.0
            volume = message.get("volume_trade_for_the_day", 0) or 0
            last_traded_qty = message.get("last_traded_quantity", 0) or 0

            # Previous close — use close_price from tick, or our stored value
            prev_close = close if close > 0 else self._prev_closes.get(symbol, ltp)
            if prev_close <= 0:
                prev_close = ltp

            change_pts = round(ltp - prev_close, 2)
            pct_change = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0

            # ─── Write to cache ──────────────────────────────
            is_index = symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")
            if is_index:
                # Index display name mapping
                display_names = {
                    "NIFTY": ("NIFTY50", "NIFTY 50"),
                    "BANKNIFTY": ("BANKNIFTY", "BANK NIFTY"),
                    "FINNIFTY": ("FINNIFTY", "FIN NIFTY"),
                    "SENSEX": ("SENSEX", "SENSEX"),
                }
                idx_code, idx_disp = display_names.get(symbol, (symbol, symbol))
                cache.set(f"index:{idx_code}:quote", {
                    "index_name": idx_code,
                    "display_name": idx_disp,
                    "ltp": round(ltp, 2),
                    "prev_close": round(prev_close, 2),
                    "change_pts": change_pts,
                    "pct_change": pct_change,
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "volume": volume,
                })
            else:
                cache.set(f"stock:{symbol}:quote", {
                    "symbol": symbol,
                    "ltp": round(ltp, 2),
                    "prev_close": round(prev_close, 2),
                    "change_pts": change_pts,
                    "pct_change": pct_change,
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": volume,
                    "last_traded_qty": last_traded_qty,
                })

            # ─── Feed CVD Engine (stocks only) ───────────────
            if not is_index and last_traded_qty > 0:
                # Extract Level 2 depth
                best_5_buy = message.get("best_5_buy_data", [])
                best_5_sell = message.get("best_5_sell_data", [])

                best_bid = 0.0
                best_ask = 0.0
                bid_qty_5l = 0
                ask_qty_5l = 0

                if best_5_buy:
                    best_bid = (best_5_buy[0].get("price", 0) or 0) / 100.0
                    bid_qty_5l = sum(b.get("quantity", 0) or 0 for b in best_5_buy[:5])
                if best_5_sell:
                    best_ask = (best_5_sell[0].get("price", 0) or 0) / 100.0
                    ask_qty_5l = sum(a.get("quantity", 0) or 0 for a in best_5_sell[:5])

                from synthetic_cvd_engine import process_tick
                process_tick(
                    symbol=symbol,
                    ltp=ltp,
                    last_traded_qty=last_traded_qty,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    bid_qty_5l=bid_qty_5l,
                    ask_qty_5l=ask_qty_5l,
                )

            # ─── Update meta ─────────────────────────────────
            self._last_tick_ts = time.time()
            self._tick_count += 1

            # Update meta every 100 ticks to avoid excessive writes
            if self._tick_count % 100 == 0:
                self._update_status(connected=True)

        except Exception as e:
            # Never let a tick processing error kill the WebSocket
            if self._tick_count % 1000 == 0:
                logger.warning(f"Tick processing error (sample): {e}")

    def _on_error(self, wsapp, error):
        """Called on WebSocket error."""
        logger.error(f"Angel One WebSocket error: {error}")
        self._connected = False
        self._update_status(connected=False)

    def _on_close(self, wsapp, close_status, close_msg):
        """Called when WebSocket disconnects."""
        logger.warning(f"Angel One WebSocket closed: {close_status} — {close_msg}")
        self._connected = False
        self._update_status(connected=False)

    def _update_status(self, connected: bool):
        """Update meta:ws_status in cache."""
        cache.set("meta:ws_status", {
            "connected": connected,
            "last_tick_ts": self._last_tick_ts,
            "subscribed_count": self._subscribed_count,
            "total_ticks": self._tick_count,
        })


# ─── Singleton ───────────────────────────────────────────────
angel_ws_stream = AngelWebSocketStream()
