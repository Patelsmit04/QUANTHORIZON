"""
INTRADAY STRATEGY ENGINE — background scanner
================================================
StrategyEngine, modeled directly on smc_scanner.SMCScannerEngine: a background daemon
thread, candle-close detection, in-memory dedup, dispatch via signal_journal.log_notification
+ ws_broadcast.broadcast_sync. Runs the 6 rule-based strategies from strategy_engine_rules.py
against Nifty 50 / Bank Nifty / Sensex and a rotating slice of the F&O stock universe.

Design notes (see plan for full rationale):
- Chain fetches are lazy — only the single chosen candidate per (asset, tick) triggers a live
  option-chain fetch, not every candidate. Strategy F additionally throttles to ~once/day per
  symbol via iv_history_tracker.has_recorded_iv_today(), since it needs a chain fetch just to
  record IV history (not only to fire), and 230 stocks x every-5-min would be a large,
  avoidable increase in NSE scraping load.
- Sensex has no live option chain (BSE-traded — see options_chain_provider.py). Strategies
  A/B/C fall back to a synthetic ATM strike/expiry for Sensex (option_strike_utils.py);
  Strategy F simply excludes Sensex (no IV to read).
- ORB fires at most once per (asset, direction) per day — tracked separately from the
  general 30-minute dedup window, since the spec calls this out explicitly.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from env_utils import get_ist_now
from fo_universe import get_canonical_fo_tickers
from intraday_data_provider import fetch_intraday_ohlc
from strategy_manager import get_strategy
from signal_journal import log_notification
import ws_broadcast
from vix_provider import fetch_india_vix
from options_chain_provider import fetch_index_option_chain
from stock_derivatives_provider import (
    fetch_stock_option_chain,
    fetch_stock_futures_snapshot,
    record_oi_snapshot,
    get_oi_change_15min,
    reset_oi_history,
)
from iv_history_tracker import record_daily_iv, is_in_lower_iv_percentile, has_recorded_iv_today
from event_calendar import has_high_impact_event_within
import option_strike_utils as strike_utils
import strategy_engine_rules as rules

logger = logging.getLogger("StrategyEngine")

INDEX_TICKERS = {"NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
INDEX_DISPLAY_NAMES = {"NIFTY50": "NIFTY 50", "BANKNIFTY": "BANK NIFTY", "SENSEX": "SENSEX"}
INDEX_CHAIN_SUPPORTED = {"NIFTY50", "BANKNIFTY"}  # Sensex has no live chain — see module docstring

STRATEGY_IDS = {
    "vwap_pullback": "vwap-pullback-v1",
    "breakdown_spike": "breakdown-spike-v1",
    "orb": "orb-v1",
    "oi_surge": "oi-surge-v1",
    "death_cross": "death-cross-v1",
    "volatility_straddle": "volatility-straddle-v1",
}

DEDUP_WINDOW_MINUTES = 30
STOCK_BATCH_SIZE = 20  # rotate through the ~230-stock F&O universe across ticks, not all at once
SCAN_POLL_SECONDS = 60


def _get_atm_iv(chain: Dict[str, Any], spot: float) -> Optional[float]:
    """Average of CE/PE IV at the ATM strike, using only verified (>0) legs. None if neither
    leg has a verified IV — never estimates from an unpriced leg."""
    atm_strike = strike_utils.get_atm_strike_from_chain(chain, spot)
    if atm_strike is None:
        return None
    row = next((s for s in chain["strikes"] if s["strike_price"] == atm_strike), None)
    if not row:
        return None
    ivs = [leg["iv"] for leg in (row.get("ce"), row.get("pe")) if leg and leg.get("iv_verified")]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


class StrategyEngine:
    def __init__(self):
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._last_candle_time: Dict[Tuple[str, str], Any] = {}
        self._last_alert_time: Dict[Tuple[str, str], datetime] = {}
        self._orb_levels: Dict[str, Dict[str, Any]] = {}
        self._orb_fired_today: set = set()
        self._session_date: Optional[str] = None
        self._stock_rotation_offset = 0

    # -- lifecycle -----------------------------------------------------

    def start_background_worker(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="StrategyEngine")
        self._thread.start()
        logger.info("Intraday Strategy Engine thread started.")

    def stop_background_worker(self):
        self._is_running = False

    def _worker_loop(self):
        while self._is_running:
            try:
                self.run_scan_pass()
            except Exception as e:
                logger.error(f"Strategy Engine error during scan pass: {e}")
            time.sleep(SCAN_POLL_SECONDS)

    # -- session bookkeeping --------------------------------------------

    def _reset_for_new_session_if_needed(self, now: datetime):
        today_str = now.strftime("%Y-%m-%d")
        if self._session_date != today_str:
            self._session_date = today_str
            self._orb_levels = {}
            self._orb_fired_today = set()
            reset_oi_history()
            logger.info(f"Strategy Engine: new session {today_str} — ORB levels and OI history reset.")

    def _is_strategy_enabled(self, strategy_key: str, scope: str) -> bool:
        try:
            strat = get_strategy(STRATEGY_IDS[strategy_key])
            if not strat or not strat.get("is_active", True):
                return False
            return bool(strat.get("scope_toggles", {}).get(scope, False))
        except Exception:
            return False

    # -- main scan pass ---------------------------------------------------

    def run_scan_pass(self):
        now = get_ist_now()
        if now.weekday() >= 5:
            return
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if not (market_open <= now <= market_close):
            return

        self._reset_for_new_session_if_needed(now)
        past_eod = rules.is_past_eod_cutoff(now)
        vix_value, _vix_regime = fetch_india_vix()

        self._scan_indices(now, vix_value, past_eod)
        self._scan_stocks(now, vix_value, past_eod)

    # -- indices ------------------------------------------------------------

    def _scan_indices(self, now: datetime, vix_value: Optional[float], past_eod: bool):
        for asset, ticker in INDEX_TICKERS.items():
            df5 = fetch_intraday_ohlc(ticker, interval="5m", period="5d")
            if df5 is None:
                continue

            key5 = (asset, "5m")
            latest_candle_time = df5.index[-1]
            if self._last_candle_time.get(key5) == latest_candle_time:
                continue
            self._last_candle_time[key5] = latest_candle_time

            if past_eod:
                continue

            candidates: List[Dict[str, Any]] = []

            today_str = now.strftime("%Y-%m-%d")
            orb_state = self._orb_levels.get(asset)
            if orb_state is None or orb_state.get("date") != today_str:
                levels = rules.compute_orb_levels(df5, now.date())
                if levels:
                    orb_state = {"date": today_str, **levels}
                    self._orb_levels[asset] = orb_state

            if orb_state and self._is_strategy_enabled("orb", "indices"):
                alert = rules.evaluate_orb(df5, orb_state["orb_high"], orb_state["orb_low"])
                if alert:
                    fired_key = (today_str, asset, alert["direction"])
                    if fired_key not in self._orb_fired_today:
                        self._orb_fired_today.add(fired_key)
                        candidates.append(alert)

            if self._is_strategy_enabled("vwap_pullback", "indices"):
                alert = rules.evaluate_vwap_pullback(df5)
                if alert:
                    candidates.append(alert)

            if self._is_strategy_enabled("breakdown_spike", "indices"):
                alert = rules.evaluate_breakdown_spike(df5)
                if alert:
                    candidates.append(alert)

            if self._is_strategy_enabled("oi_surge", "indices"):
                oi_change = get_oi_change_15min(asset, now=now)
                alert = rules.evaluate_oi_surge(df5, oi_change)
                if alert:
                    candidates.append(alert)

            if self._is_strategy_enabled("death_cross", "indices"):
                df15 = fetch_intraday_ohlc(ticker, interval="15m", period="1mo")
                if df15 is not None:
                    oi_change = get_oi_change_15min(asset, now=now)
                    alert = rules.evaluate_death_cross(df15, oi_change)
                    if alert:
                        candidates.append(alert)

            if asset in INDEX_CHAIN_SUPPORTED and self._is_strategy_enabled("volatility_straddle", "indices"):
                straddle_alert = self._maybe_evaluate_straddle(
                    asset, spot=float(df5["Close"].iloc[-1]),
                    fetch_chain=lambda: fetch_index_option_chain(asset), now=now,
                )
                if straddle_alert:
                    candidates.append(straddle_alert)

            if not candidates:
                continue

            spot = float(df5["Close"].iloc[-1])
            chosen = self._pick_priority(candidates, df5)
            chain = chosen.pop("_chain", None)
            if chain is None and asset in INDEX_CHAIN_SUPPORTED:
                chain = fetch_index_option_chain(asset)
            self._dispatch(chosen, asset, INDEX_DISPLAY_NAMES[asset], spot, chain, now, vix_value)

    # -- stocks ---------------------------------------------------------------

    def _scan_stocks(self, now: datetime, vix_value: Optional[float], past_eod: bool):
        a_enabled = self._is_strategy_enabled("vwap_pullback", "stocks")
        b_enabled = self._is_strategy_enabled("breakdown_spike", "stocks")
        c_enabled = self._is_strategy_enabled("orb", "stocks")
        d_enabled = self._is_strategy_enabled("oi_surge", "stocks")
        e_enabled = self._is_strategy_enabled("death_cross", "stocks")
        f_enabled = self._is_strategy_enabled("volatility_straddle", "stocks")
        if not (a_enabled or b_enabled or c_enabled or d_enabled or e_enabled or f_enabled):
            return

        universe = get_canonical_fo_tickers()
        if not universe:
            return
        batch = self._next_stock_batch(universe)

        for ticker in batch:
            if not self._is_running:
                break
            symbol = ticker.replace(".NS", "").upper()
            try:
                self._scan_one_stock(symbol, ticker, now, vix_value, past_eod,
                                     a_enabled, b_enabled, c_enabled, d_enabled, e_enabled, f_enabled)
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
            time.sleep(0.2)  # stagger — same rate-limit compromise smc_scanner.py makes

    def _next_stock_batch(self, universe: List[str]) -> List[str]:
        n = len(universe)
        start = self._stock_rotation_offset % n
        end = start + STOCK_BATCH_SIZE
        batch = (universe[start:end] if end <= n else universe[start:] + universe[:end - n])
        self._stock_rotation_offset = end % n
        return batch

    def _scan_one_stock(self, symbol: str, ticker: str, now: datetime, vix_value: Optional[float],
                         past_eod: bool, a_enabled: bool, b_enabled: bool, c_enabled: bool,
                         d_enabled: bool, e_enabled: bool, f_enabled: bool):
        if d_enabled or e_enabled:
            fut = fetch_stock_futures_snapshot(symbol)
            if fut and fut.get("open_interest"):
                record_oi_snapshot(symbol, fut["open_interest"], ts=now)

        df5 = fetch_intraday_ohlc(ticker, interval="5m", period="5d")
        if df5 is None:
            return

        key5 = (symbol, "5m")
        latest_candle_time = df5.index[-1]
        if self._last_candle_time.get(key5) == latest_candle_time:
            return
        self._last_candle_time[key5] = latest_candle_time

        if past_eod:
            return

        candidates: List[Dict[str, Any]] = []

        if a_enabled:
            alert = rules.evaluate_vwap_pullback(df5)
            if alert:
                candidates.append(alert)

        if b_enabled:
            alert = rules.evaluate_breakdown_spike(df5)
            if alert:
                candidates.append(alert)

        if c_enabled:
            today_str = now.strftime("%Y-%m-%d")
            orb_state = self._orb_levels.get(symbol)
            if orb_state is None or orb_state.get("date") != today_str:
                levels = rules.compute_orb_levels(df5, now.date())
                if levels:
                    orb_state = {"date": today_str, **levels}
                    self._orb_levels[symbol] = orb_state

            if orb_state:
                alert = rules.evaluate_orb(df5, orb_state["orb_high"], orb_state["orb_low"])
                if alert:
                    fired_key = (today_str, symbol, alert["direction"])
                    if fired_key not in self._orb_fired_today:
                        self._orb_fired_today.add(fired_key)
                        candidates.append(alert)

        if d_enabled:
            oi_change = get_oi_change_15min(symbol, now=now)
            alert = rules.evaluate_oi_surge(df5, oi_change)
            if alert:
                candidates.append(alert)

        if e_enabled:
            df15 = fetch_intraday_ohlc(ticker, interval="15m", period="1mo")
            if df15 is not None:
                oi_change = get_oi_change_15min(symbol, now=now)
                alert = rules.evaluate_death_cross(df15, oi_change)
                if alert:
                    candidates.append(alert)

        if f_enabled:
            straddle_alert = self._maybe_evaluate_straddle(
                symbol, spot=float(df5["Close"].iloc[-1]),
                fetch_chain=lambda: fetch_stock_option_chain(symbol), now=now,
            )
            if straddle_alert:
                candidates.append(straddle_alert)

        if not candidates:
            return

        spot = float(df5["Close"].iloc[-1])
        chosen = self._pick_priority(candidates, df5)
        chain = chosen.pop("_chain", None)
        if chain is None:
            chain = fetch_stock_option_chain(symbol)
        self._dispatch(chosen, symbol, symbol, spot, chain, now, vix_value)

    # -- shared: Strategy F --------------------------------------------------

    def _maybe_evaluate_straddle(self, asset_key: str, spot: float, fetch_chain, now: datetime) -> Optional[Dict[str, Any]]:
        """Throttled to ~once/day per asset unless a qualifying event is within 48h — a full
        chain fetch is needed just to record today's IV, let alone to fire, so this avoids
        hitting NSE for every asset on every 5-minute tick (see module docstring)."""
        has_event = has_high_impact_event_within(asset_key, hours=48, now=now)
        if not has_event and has_recorded_iv_today(asset_key):
            return None

        chain = fetch_chain()
        if not chain:
            return None

        atm_iv = _get_atm_iv(chain, spot)
        if atm_iv is None:
            return None

        record_daily_iv(asset_key, atm_iv)
        if not has_event:
            return None  # recorded for history-building; not attempting to fire today

        in_low_pct = is_in_lower_iv_percentile(asset_key, atm_iv)
        alert = rules.evaluate_volatility_straddle(in_low_pct, has_event)
        if alert:
            alert["_chain"] = chain  # reuse in _dispatch instead of re-fetching
        return alert

    # -- priority override ----------------------------------------------------

    def _pick_priority(self, candidates: List[Dict[str, Any]], df5: pd.DataFrame) -> Dict[str, Any]:
        """Spec: 'prioritize the one with higher volume confirmation.' Only Breakdown Spike
        computes its own volume_spike_ratio (volume confirmation is central to its own
        condition); every other candidate falls back to the same generic current-candle vs
        recent-5-candle ratio so they're compared on the same basis."""
        if len(candidates) == 1:
            return candidates[0]

        generic_ratio = 0.0
        if len(df5) >= 6:
            baseline = float(df5["Volume"].iloc[-6:-1].mean())
            if baseline > 0:
                generic_ratio = float(df5["Volume"].iloc[-1]) / baseline

        candidates.sort(key=lambda c: c.get("volume_spike_ratio", generic_ratio), reverse=True)
        return candidates[0]

    # -- dedup ------------------------------------------------------------------

    def _check_dedup(self, strategy_key: str, asset: str, now: datetime) -> bool:
        last = self._last_alert_time.get((strategy_key, asset))
        if last and (now - last).total_seconds() < DEDUP_WINDOW_MINUTES * 60:
            return False
        return True

    def _mark_dedup(self, strategy_key: str, asset: str, now: datetime):
        self._last_alert_time[(strategy_key, asset)] = now

    # -- dispatch ------------------------------------------------------------------

    def _dispatch(self, alert: Dict[str, Any], asset_key: str, asset_display: str, spot: float,
                  chain: Optional[Dict[str, Any]], now: datetime, vix_value: Optional[float]):
        strategy_key = alert["strategy_key"]

        if not self._check_dedup(strategy_key, asset_key, now):
            logger.debug(f"{asset_key} {strategy_key}: suppressed — already active within {DEDUP_WINDOW_MINUTES}min.")
            return

        option_type = alert["option_type"]
        vix_side = "BOTH" if option_type == "BOTH" else alert["direction"]
        if not rules.vix_gate(vix_value, vix_side):
            logger.debug(f"{asset_key} {strategy_key}: suppressed by VIX gate (VIX={vix_value}).")
            return

        otm_steps = alert.get("otm_steps", 0)
        if chain:
            expiry = strike_utils.resolve_expiry(chain, now)
            if option_type == "BOTH":
                strike = strike_utils.get_atm_strike_from_chain(chain, spot)
            elif otm_steps > 0:
                strike = strike_utils.get_otm_strike_from_chain(chain, spot, option_type, steps=otm_steps)
            else:
                strike = strike_utils.get_atm_strike_from_chain(chain, spot)
        else:
            expiry = strike_utils.resolve_synthetic_expiry(now)
            if option_type == "BOTH":
                strike = strike_utils.get_synthetic_atm_strike(spot)
            elif otm_steps > 0:
                strike = strike_utils.get_synthetic_otm_strike(spot, option_type, steps=otm_steps)
            else:
                strike = strike_utils.get_synthetic_atm_strike(spot)

        if strike is None or expiry is None:
            logger.debug(f"{asset_key} {strategy_key}: could not resolve strike/expiry — skipping.")
            return

        strike_label = f"{strike:g} CE + {strike:g} PE" if option_type == "BOTH" else f"{strike:g} {option_type}"
        action = {"CE": "BUY ATM CALL", "PE": "BUY ATM PUT", "BOTH": "BUY CALL + BUY PUT"}[option_type]

        rationale = alert["rationale"]
        quantity_note = " Position size capped at 1 lot (Bank Nifty)." if asset_key == "BANKNIFTY" else ""

        target = alert.get("target")
        target_display = target if target is not None else alert.get("target_text")
        stop_loss = alert.get("stop_loss")
        stop_loss_display = stop_loss if stop_loss is not None else "Position-management exit — see rationale."

        payload = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S IST"),
            "strategy_name": alert["strategy_name"],
            "asset": asset_display,
            "direction": alert["direction"],
            "action": action,
            "strike": strike_label,
            "expiry": expiry,
            "target": target_display,
            "stop_loss": stop_loss_display,
            "rationale": rationale + quantity_note,
            "risk_warning": "Max loss = premium paid. Trade at your own risk.",
        }

        title = f"{asset_display} — {alert['strategy_name']} — {action}"
        message = f"{strike_label} ({expiry}). Target: {target_display}. SL: {stop_loss_display}. {rationale}"

        notif = log_notification(notif_type="strategy_engine_alert", title=title, message=message, payload=payload)
        ws_broadcast.broadcast_sync({"type": "notification", **notif})

        self._mark_dedup(strategy_key, asset_key, now)
        logger.info(f"STRATEGY ENGINE ALERT: {title}")


# Global singleton, same pattern as smc_scanner.smc_scanner
strategy_engine = StrategyEngine()
