"""
CONTINUOUS MULTI-TIMEFRAME SMC SCANNER ENGINE
==============================================
Monitors tracked stocks and indices across multiple timeframes (1m, 3m, 5m, 15m, 1h, 4h, 1d):
- Candle-close detection per (symbol, timeframe)
- Multi-timeframe SMC pattern detection via smc_helpers.py / smc_strategy.py
- Setup deduplication per (symbol, timeframe)
- Live WebSocket & Notification Bell dispatch
- Scope-toggle gating via strategy_manager (smc-institutional-v1)
"""

import time
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import yfinance as yf

from fo_universe import get_canonical_fo_tickers
from smc_strategy import evaluate_signal
from strategy_manager import get_strategy
from signal_journal import log_notification
import ws_broadcast
from datetime import timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


def is_market_open_ist() -> bool:
    now = get_ist_now()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

logger = logging.getLogger("SMCScanner")

SMC_STRATEGY_ID = "smc-institutional-v1"

SUPPORTED_TIMEFRAMES: Dict[str, Tuple[str, str]] = {
    "1m": ("1d", "1m"),
    "3m": ("1d", "2m"),   # yf uses 2m as closest proxy for 3m
    "5m": ("5d", "5m"),
    "15m": ("5d", "15m"),
    "1h": ("1mo", "1h"),
    "4h": ("1mo", "1h"),  # 4h aggregated from 1h
    "1d": ("3mo", "1d"),
}

INDEX_MAP = {
    "^NSEI": "NIFTY50",
    "^NSEBANK": "BANKNIFTY",
    "^BSESN": "SENSEX",
}


class SMCScannerEngine:
    def __init__(self):
        self._last_candle_time: Dict[Tuple[str, str], Any] = {}
        self._last_alerted_setup: Dict[Tuple[str, str], str] = {}
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

    def start_background_worker(self):
        """Launches continuous background worker thread if not already running."""
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="SMCBackgroundScanner")
        self._thread.start()
        logger.info("Continuous Multi-Timeframe SMC Scanner thread started.")

    def stop_background_worker(self):
        self._is_running = False

    def _worker_loop(self):
        while self._is_running:
            try:
                self.run_scan_pass()
            except Exception as e:
                logger.error(f"SMC Scanner error during scan pass: {e}")

            # Sleep between scan passes
            time.sleep(30)

    def is_smc_scope_enabled(self, target_type: str) -> bool:
        """Check whether Scope A (stocks) or Scope B (indices) toggle is ON for SMC."""
        try:
            strat = get_strategy(SMC_STRATEGY_ID)
            if not strat or not strat.get("is_active", True):
                return False
            toggles = strat.get("scope_toggles", {})
            return bool(toggles.get(target_type, False))
        except Exception:
            return False

    def run_scan_pass(self):
        """Single scan pass over enabled scopes & timeframes with candle-close detection."""
        stocks_enabled = self.is_smc_scope_enabled("stocks")
        indices_enabled = self.is_smc_scope_enabled("indices")

        if not stocks_enabled and not indices_enabled:
            return  # both toggled OFF — skip scanning

        symbols_to_scan = []
        if stocks_enabled:
            symbols_to_scan.extend(get_canonical_fo_tickers()[:50])  # Primary F&O universe batch
        if indices_enabled:
            symbols_to_scan.extend(list(INDEX_MAP.keys()))

        for symbol in symbols_to_scan:
            if not self._is_running:
                break
            human_symbol = INDEX_MAP.get(symbol, symbol)
            self._scan_symbol_timeframes(symbol, human_symbol)
            time.sleep(0.2)  # rate-limit stagger

    def _scan_symbol_timeframes(self, symbol: str, human_symbol: str):
        for tf, (period, interval) in SUPPORTED_TIMEFRAMES.items():
            try:
                df = self._fetch_ohlc(symbol, period, interval)
                if df is None or df.empty or len(df) < 10:
                    continue

                latest_candle_time = df.index[-1]
                key = (symbol, tf)

                # Candle-close check: only evaluate if candle timestamp has advanced
                if self._last_candle_time.get(key) == latest_candle_time:
                    continue  # candle hasn't closed yet — skip re-evaluation

                self._last_candle_time[key] = latest_candle_time
                setup = evaluate_signal(df)

                if not setup:
                    self._last_alerted_setup.pop(key, None)
                    continue

                # Setup detected — check deduplication
                sig = setup.get("signal", "")
                entry = setup.get("entry", float(df["Close"].iloc[-1]))
                tp_pct = setup.get("tp_pct", 1.5)
                sl_pct = setup.get("sl_pct", 0.75)
                reason = setup.get("reason", "SMC Pattern Confirmed")

                direction = "Bullish Setup" if "BUY" in sig else "Bearish Setup"
                tp_price = round(entry * (1 + tp_pct / 100) if "BUY" in sig else entry * (1 - tp_pct / 100), 2)
                sl_price = round(entry * (1 - sl_pct / 100) if "BUY" in sig else entry * (1 + sl_pct / 100), 2)

                setup_fingerprint = f"{sig}_{round(entry, 2)}_{tf}_{latest_candle_time}"
                if self._last_alerted_setup.get(key) == setup_fingerprint:
                    continue  # already alerted for this exact setup & candle

                self._last_alerted_setup[key] = setup_fingerprint

                # Dispatch live notification
                title = f"{human_symbol} — SMC ({tf}) — {direction}"
                message = f"Entry ₹{entry:,.2f} / TP ₹{tp_price:,.2f} ({tp_pct}%) / SL ₹{sl_price:,.2f} ({sl_pct}%) — {reason}"

                logger.info(f"SMC ALERT DISPATCH: {title} | {message}")

                notif = log_notification(
                    title=title,
                    message=message,
                    payload={
                        "symbol": human_symbol,
                        "timeframe": tf,
                        "signal": sig,
                        "entry": entry,
                        "tp_price": tp_price,
                        "sl_price": sl_price,
                        "tp_pct": tp_pct,
                        "sl_pct": sl_pct,
                        "reason": reason,
                    }
                )
                ws_broadcast.broadcast_sync({"type": "notification", **notif})

            except Exception as e:
                logger.debug(f"Error scanning {symbol} ({tf}): {e}")

    def _fetch_ohlc(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
            if df is None or df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna(subset=["Close", "Open", "High", "Low"])
        except Exception:
            return None


# Global singleton scanner instance
smc_scanner = SMCScannerEngine()
