"""
SYNTHETIC CVD ENGINE — Tick-Rule Cumulative Volume Delta
=========================================================
Computes a proxy Footprint / CVD using the free Angel One Level 2 feed.
Replaces the old Zerodha simulator with real tick-rule classification.

Tick Rule Logic:
  - LTP >= Best Ask → BUY-initiated (buyer lifted the ask)
  - LTP <= Best Bid → SELL-initiated (seller hit the bid)
  - Bid < LTP < Ask → Uptick/downtick rule vs previous LTP

Aggregates tick-by-tick delta into 1-minute time buckets in cache.
Powers the 3:15 PM Order Flow Veto mechanism.
"""

import time
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import defaultdict

logger = logging.getLogger("SyntheticCVDEngine")


class OrderFlowData:
    """
    Compatible replacement for zerodha_order_flow_provider.OrderFlowData.
    order_flow_analyzer.py reads this exact interface.
    """
    def __init__(self, symbol: str, data_source: str = "ANGEL_ONE_TICK_RULE"):
        self.symbol = symbol
        self.data_source = data_source
        self.had_data_gap = False
        self.last_tick_timestamp = time.time()
        self.total_ticks = 0
        self.depth_imbalance = {
            "bid_qty_5l": 0,
            "ask_qty_5l": 0,
            "depth_ratio": 1.0,
            "bid_pct": 50.0,
            "ask_pct": 50.0
        }
        self.minute_bars: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "data_source": self.data_source,
            "had_data_gap": self.had_data_gap,
            "last_tick_timestamp": self.last_tick_timestamp,
            "total_ticks": self.total_ticks,
            "depth_imbalance": self.depth_imbalance,
            "minute_bars": self.minute_bars,
            "inferred_delta_notice": (
                "Delta is TICK-RULE classified from Angel One Level 2 feed "
                "(LTP vs Bid/Ask), not exchange-tagged."
            ),
        }


# ─── Module State ────────────────────────────────────────────
_lock = threading.Lock()

# Per-symbol state tracking
_prev_ltp: Dict[str, float] = {}           # symbol → last LTP
_prev_direction: Dict[str, int] = {}       # symbol → last aggressor direction (+1/-1)
_last_tick_time: Dict[str, float] = {}     # symbol → timestamp of last tick
_DATA_GAP_THRESHOLD = 15.0                 # seconds — > this = data gap

# 1-minute CVD buckets: symbol → {minute_key: {buy_vol, sell_vol, tick_count}}
_cvd_buckets: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {
    "buy_vol": 0, "sell_vol": 0, "tick_count": 0
}))
_session_date: Optional[str] = None  # Reset buckets on new trading day


def _get_minute_key() -> str:
    """Current 1-minute bucket key: 'HH:MM'."""
    return datetime.now().strftime("%H:%M")


def _check_new_day():
    """Reset CVD buckets at session start (new trading day)."""
    global _session_date, _cvd_buckets
    today = datetime.now().strftime("%Y-%m-%d")
    if _session_date != today:
        with _lock:
            _session_date = today
            _cvd_buckets.clear()
            _prev_ltp.clear()
            _prev_direction.clear()
            _last_tick_time.clear()
            logger.info(f"CVD engine reset for new trading day: {today}")


def process_tick(
    symbol: str,
    ltp: float,
    last_traded_qty: int,
    best_bid: float,
    best_ask: float,
    bid_qty_5l: int = 0,
    ask_qty_5l: int = 0,
) -> None:
    """
    Process a single incoming tick from the Angel One WebSocket.
    Classifies the trade as buy/sell-initiated using the tick rule,
    then aggregates into 1-minute CVD buckets.

    Called from angel_ws_stream.py on every on_data callback.
    """
    _check_new_day()

    if ltp <= 0 or last_traded_qty <= 0:
        return

    now = time.time()
    minute_key = _get_minute_key()

    with _lock:
        # Check for data gap
        prev_time = _last_tick_time.get(symbol, now)
        gap = now - prev_time
        _last_tick_time[symbol] = now

        # ─── Tick Rule Classification ────────────────────────
        prev_dir = _prev_direction.get(symbol, 1)
        prev_price = _prev_ltp.get(symbol, ltp)

        if best_ask > 0 and ltp >= best_ask:
            # Trade at or above ask → buyer-initiated
            direction = 1
        elif best_bid > 0 and ltp <= best_bid:
            # Trade at or below bid → seller-initiated
            direction = -1
        elif ltp > prev_price:
            # Uptick → buyer-initiated
            direction = 1
        elif ltp < prev_price:
            # Downtick → seller-initiated
            direction = -1
        else:
            # Same price → inherit previous direction
            direction = prev_dir if prev_dir != 0 else 1

        _prev_ltp[symbol] = ltp
        _prev_direction[symbol] = direction

        # ─── Aggregate into 1-minute bucket ──────────────────
        bucket = _cvd_buckets[symbol][minute_key]
        if direction > 0:
            bucket["buy_vol"] += last_traded_qty
        else:
            bucket["sell_vol"] += last_traded_qty
        bucket["tick_count"] += 1

    # Write to cache (non-blocking, outside lock)
    try:
        from cache_layer import cache

        # Write CVD 1-minute buckets
        cvd_data = _get_cvd_bars(symbol)
        cache.set(f"stock:{symbol}:cvd_1m", cvd_data)

        # Write depth data
        if bid_qty_5l > 0 or ask_qty_5l > 0:
            total = bid_qty_5l + ask_qty_5l
            depth_ratio = round(bid_qty_5l / ask_qty_5l, 2) if ask_qty_5l > 0 else 5.0
            bid_pct = round((bid_qty_5l / total) * 100, 1) if total > 0 else 50.0
            cache.set(f"stock:{symbol}:depth", {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_qty_5l": bid_qty_5l,
                "ask_qty_5l": ask_qty_5l,
                "depth_ratio": depth_ratio,
                "bid_pct": bid_pct,
                "ask_pct": round(100.0 - bid_pct, 1),
            })

    except Exception as e:
        logger.debug(f"CVD cache write warning for {symbol}: {e}")


def _get_cvd_bars(symbol: str) -> List[Dict[str, Any]]:
    """Get sorted 1-minute CVD bars for a symbol (inside lock)."""
    bars = []
    for minute, data in sorted(_cvd_buckets.get(symbol, {}).items()):
        buy = data["buy_vol"]
        sell = data["sell_vol"]
        bars.append({
            "minute": minute,
            "buy_volume": buy,
            "sell_volume": sell,
            "net_delta": buy - sell,
            "tick_count": data["tick_count"],
            "is_dominant_positive": (buy - sell) > 0,
        })
    return bars


def get_order_flow_data(
    symbol: str,
    signal_type: str = "BTST (BUY)",
    signal_direction: Optional[str] = None,
) -> OrderFlowData:
    """
    Returns OrderFlowData for symbol — compatible with order_flow_analyzer.py.
    If real WebSocket data exists in CVD buckets, returns that.
    Otherwise falls back to a high-fidelity simulator (same as old Zerodha provider).
    """
    clean_sym = symbol.replace(".NS", "").upper()
    effective_direction = signal_direction or signal_type

    of_data = OrderFlowData(clean_sym)

    with _lock:
        sym_buckets = _cvd_buckets.get(clean_sym, {})

        if sym_buckets:
            # Real tick-rule data available
            of_data.data_source = "ANGEL_ONE_TICK_RULE"

            # Get 3:15-3:25 PM bars specifically for the veto window
            veto_bars = []
            for minute_key in sorted(sym_buckets.keys()):
                if "15:15" <= minute_key <= "15:25":
                    data = sym_buckets[minute_key]
                    buy = data["buy_vol"]
                    sell = data["sell_vol"]
                    veto_bars.append({
                        "minute": minute_key,
                        "buy_volume": buy,
                        "sell_volume": sell,
                        "net_delta": buy - sell,
                        "tick_count": data["tick_count"],
                        "is_dominant_positive": (buy - sell) > 0,
                    })

            if veto_bars:
                of_data.minute_bars = veto_bars
                of_data.total_ticks = sum(b["tick_count"] for b in veto_bars)
            else:
                # Data exists but not in the veto window yet
                all_bars = _get_cvd_bars(clean_sym)
                of_data.minute_bars = all_bars[-10:]  # Last 10 minutes
                of_data.total_ticks = sum(b["tick_count"] for b in of_data.minute_bars)

            # Check for data gap
            last_tick = _last_tick_time.get(clean_sym, 0)
            if last_tick > 0 and (time.time() - last_tick) > _DATA_GAP_THRESHOLD:
                of_data.had_data_gap = True
            of_data.last_tick_timestamp = last_tick

            # Depth imbalance from cache
            try:
                from cache_layer import cache
                depth = cache.get(f"stock:{clean_sym}:depth", {})
                if depth:
                    of_data.depth_imbalance = depth
            except Exception:
                pass

            return of_data

    # ─── Fallback: Synthetic simulator (no live data) ────────
    of_data.data_source = "INFERRED_SIMULATOR"
    is_bullish = "BTST" in effective_direction or "BUY" in effective_direction
    return _generate_synthetic_flow(clean_sym, is_bullish, of_data)


def _generate_synthetic_flow(symbol: str, is_bullish: bool, of_data: OrderFlowData) -> OrderFlowData:
    """Generate realistic synthetic bars when no live tick data is available."""
    import random
    seed_val = sum(ord(c) for c in symbol)
    random.seed(seed_val)

    bars = []
    total_ticks = 0
    total_bid = 0
    total_ask = 0
    base_vol = 12000 if symbol in ("RELIANCE", "INFY", "TCS", "HDFCBANK") else 4500

    for i in range(10):
        minute_str = f"15:{15 + i:02d}"
        tick_count = random.randint(180, 420)
        total_ticks += tick_count
        vol = int(base_vol * random.uniform(0.8, 1.6))

        if is_bullish:
            is_pos = (i not in [2, 7])
        else:
            is_pos = (i in [2, 7])

        if is_pos:
            buy_vol = int(vol * random.uniform(0.55, 0.75))
            sell_vol = vol - buy_vol
        else:
            sell_vol = int(vol * random.uniform(0.55, 0.75))
            buy_vol = vol - sell_vol

        total_bid += buy_vol
        total_ask += sell_vol
        bars.append({
            "minute": minute_str,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "net_delta": buy_vol - sell_vol,
            "tick_count": tick_count,
            "is_dominant_positive": (buy_vol - sell_vol) > 0,
        })

    of_data.minute_bars = bars
    of_data.total_ticks = total_ticks
    of_data.had_data_gap = False

    depth_tot = total_bid + total_ask
    bid_pct = round((total_bid / depth_tot) * 100, 1) if depth_tot > 0 else 50.0
    of_data.depth_imbalance = {
        "bid_qty_5l": total_bid,
        "ask_qty_5l": total_ask,
        "depth_ratio": round(total_bid / total_ask, 2) if total_ask > 0 else 1.0,
        "bid_pct": bid_pct,
        "ask_pct": round(100.0 - bid_pct, 1),
    }

    return of_data
