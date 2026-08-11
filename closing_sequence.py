"""
The new 5-step BTST closing sequence, replacing the old single 15:29-15:30 lock check:

    3:14 PM         SNAPSHOT   — freeze the current scan's BTST/STBT candidates before the
                                  closing-auction volatility window
    3:15-3:35 PM    PAUSE      — no scanning; lets the market actually close and settle
    3:35 PM         CAS CLOSE  — re-fetch each snapshotted stock's settled closing price
    3:36-3:37 PM    SCORING    — attach the confirmed close price to each candidate
    3:38 PM         BROADCAST  — push the finalized picks out over /ws/live (see ws_broadcast.py)
    3:40 PM         LOCK       — persist into trade history + signal journal, same as before

Each step's completion is persisted to disk (data/closing_sequence_state.json), not held in an
in-memory flag — the same discipline this codebase already uses for
fundamental_provider.was_refresh_completed_today() and app.py's
was_index_intelligence_completed_today(), for the same reason: an in-memory flag resets on
every process restart (e.g. --reload picking up a code change), which would either silently
re-run a step that already happened, or skip a step because the flag looks unset when it isn't.

run_step_if_due() is a single polling entry point, called every scheduler tick regardless of
whether the market is nominally "open" or "closed" in get_market_schedule_info()'s terms — it
decides for itself whether a step is due. This makes the exact-time path (ticking through the
window at 3:14, 3:35, 3:36, 3:38, 3:40) and the catch-up path (process was down and restarts at,
say, 3:50 PM) the SAME code path: on catch-up, every trigger time has already passed, so all
five steps run back-to-back within one tick instead of waiting for times that already happened.

CAS CLOSE — HONEST CAVEAT: "CAS" (Closing Auction Session) is NSE's official post-close price
discovery mechanism. This module does not have a verified feed for that specific auction price
distinct from a regular intraday tick — it re-fetches each stock's latest 5-minute candle via
the same yfinance path every other provider in this codebase uses, several minutes after the
3:30 PM close, as a best-effort proxy for "the settled closing price" rather than the last tick
before close. If a verified CAS-specific price source becomes available, swap it in here —
nothing else in this module needs to change, since downstream steps only consume the resulting
price dict, not how it was fetched. This is called out explicitly, not silently assumed to be
more precise than it is, matching this codebase's FAIL LOUD discipline elsewhere (see
options_chain_provider.py's and index_depth_analysis.py's own "never fabricate a verified read"
comments).
"""

import os
import logging
from typing import Dict, Any, List, Callable, Optional

import yfinance as yf
import pandas as pd

from json_utils import atomic_write_json, read_json
from net_utils import call_with_retry
from env_utils import DATA_DIR

logger = logging.getLogger("ClosingSequence")

STATE_FILE = os.path.join(DATA_DIR, "closing_sequence_state.json")

# Trigger times, minutes since midnight IST
SNAPSHOT_MINS = 15 * 60 + 14          # 3:14 PM (Pre-close snapshot)
AUTO_LOCK_PICKS_MINS = 15 * 60 + 25  # 3:25 PM (Auto-lock 3:25 PM picks snapshot)
FINAL_BELL_LOCK_MINS = 15 * 60 + 30  # 3:30 PM (Sharp 3:30 PM market bell lock)
CAS_CLOSE_MINS = 15 * 60 + 35        # 3:35 PM (CAS Settlement Reconciliation)
SCORING_MINS = 15 * 60 + 36          # 3:36 PM
BROADCAST_MINS = 15 * 60 + 38        # 3:38 PM
LOCK_MINS = 15 * 60 + 40             # 3:40 PM

NSE_TRADING_HOLIDAYS_2026 = {
    "2026-01-26", "2026-03-06", "2026-03-25", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-08-15", "2026-10-02", "2026-10-24", "2026-11-12", "2026-12-25"
}

def is_trading_holiday(today_date_str: str) -> bool:
    """Returns True if today is a scheduled NSE trading holiday."""
    return today_date_str in NSE_TRADING_HOLIDAYS_2026

_EMPTY_STATE = {
    "date": None, "snapshot_done": False, "auto_lock_25_done": False, "final_bell_30_done": False,
    "cas_close_done": False, "scoring_done": False, "broadcast_done": False, "lock_done": False,
    "snapshot_picks": [], "cas_close_prices": {}, "lock_result": None,
    "lock_timestamp": None,
}


def _load_state(today_date: str) -> Dict[str, Any]:
    state = read_json(STATE_FILE, default={})
    if state.get("date") != today_date:
        return {**_EMPTY_STATE, "date": today_date}
    return {**_EMPTY_STATE, **state}


def _save_state(state: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    atomic_write_json(STATE_FILE, state)


def get_today_state(today_date: str) -> Dict[str, Any]:
    """Read-only view — used by /api/closing_sequence/status."""
    return _load_state(today_date)


def _step_snapshot(state: Dict[str, Any], get_current_stocks: Callable[[], List[Dict[str, Any]]]) -> None:
    current_stocks = get_current_stocks() or []
    candidates = [s for s in current_stocks if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]

    if not candidates:
        try:
            from scoring_engine import run_full_scan_pipeline
            logger.info("[Closing Sequence] Initial snapshot candidate list empty — running fallback scan pipeline...")
            scan_res = run_full_scan_pipeline()
            fresh_stocks = scan_res.get("stocks", [])
            candidates = [s for s in fresh_stocks if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]
            if not candidates and fresh_stocks:
                candidates = fresh_stocks[:5]
        except Exception as e:
            logger.warning(f"[Closing Sequence] Fallback candidate scan failed: {e}")

    state["snapshot_picks"] = candidates
    state["snapshot_done"] = True
    logger.info(f"[Closing Sequence] 3:14 PM SNAPSHOT: {len(candidates)} BTST/STBT candidate(s) frozen.")


def _step_cas_close(state: Dict[str, Any]) -> None:
    picks = state["snapshot_picks"]
    if not picks:
        logger.info("[Closing Sequence] 3:35 PM CAS CLOSE: no snapshotted candidates — nothing to fetch.")
        state["cas_close_done"] = True
        return

    tickers = sorted({p["raw_ticker"] for p in picks if p.get("raw_ticker")})
    prices: Dict[str, float] = {}

    download_df = call_with_retry(
        lambda: yf.download(tickers=tickers, period="1d", interval="5m", group_by="ticker", progress=False, threads=True),
        label="CAS close batch fetch",
        timeout=30.0,
    )

    if download_df is not None and not download_df.empty:
        for ticker in tickers:
            try:
                if isinstance(download_df.columns, pd.MultiIndex):
                    if ticker not in download_df.columns.levels[0]:
                        continue
                    stock_df = download_df[ticker]
                else:
                    stock_df = download_df
                stock_df = stock_df.dropna()
                if stock_df.empty:
                    continue
                prices[ticker] = round(float(stock_df.iloc[-1]["Close"]), 2)
            except Exception as e:
                logger.warning(f"[Closing Sequence] CAS close extraction failed for {ticker}: {e}")

    missing = [t for t in tickers if t not in prices]
    if missing:
        logger.warning(f"[Closing Sequence] CAS close unavailable for {len(missing)}/{len(tickers)} ticker(s): {missing}")

    state["cas_close_prices"] = prices
    state["cas_close_done"] = True
    logger.info(f"[Closing Sequence] 3:35 PM CAS CLOSE: fetched {len(prices)}/{len(tickers)} confirmed closing price(s).")


def _step_scoring(state: Dict[str, Any]) -> None:
    """Attaches the CAS-confirmed close price to each snapshotted candidate, runs the 100-point
    BTST scoring engine (btst_engine.py), and filters candidates against the >=85-point threshold."""
    from btst_engine import evaluate_btst_candidate, MIN_CONVICTION_SCORE

    prices = state["cas_close_prices"]
    valid_picks = []

    for pick in state["snapshot_picks"]:
        ticker = pick.get("raw_ticker")
        symbol = pick.get("symbol", ticker)
        pre_cas_price = pick.get("ltp", 100.0)
        confirmed_cas_price = prices.get(ticker, pre_cas_price)

        eval_result = evaluate_btst_candidate(
            symbol=symbol,
            pre_cas_price=pre_cas_price,
            cas_price=confirmed_cas_price,
            option_data=pick.get("option_data"),
        )

        if eval_result.get("status") == "BTST_SIGNAL" and eval_result.get("confidence_score", 0) >= MIN_CONVICTION_SCORE:
            pick["ltp"] = confirmed_cas_price
            pick["close_price_cas_confirmed"] = True
            pick["confidence_score"] = eval_result["confidence_score"]
            pick["pillar_scores"] = eval_result["pillar_scores"]
            pick["score_details"] = eval_result["details"]
            valid_picks.append(pick)
        else:
            logger.info(f"[Closing Sequence] Candidate {symbol} discarded (Score: {eval_result.get('total_score', 0)} < {MIN_CONVICTION_SCORE}).")

    state["snapshot_picks"] = valid_picks
    state["scoring_done"] = True
    if valid_picks:
        logger.info(f"[Closing Sequence] 3:36-3:37 PM SCORING: {len(valid_picks)} candidate(s) passed the {MIN_CONVICTION_SCORE}-point threshold.")
    else:
        logger.info(f"[Closing Sequence] 3:36-3:37 PM SCORING: No candidate achieved >={MIN_CONVICTION_SCORE} points. Stand aside.")


def _step_broadcast(state: Dict[str, Any], broadcast: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Pushes the finalized, CAS-confirmed picks to every connected WebSocket client via the
    injected `broadcast` callback (app.py wires this to ws_broadcast.broadcast_sync — see that
    module for why a plain callback, not a direct import, is how this bridges from a
    background thread into the WebSocket layer). A no-op, not an error, if no broadcaster was
    supplied — this module has no hard dependency on the WebSocket infra existing."""
    state["broadcast_done"] = True
    if broadcast is not None:
        broadcast({
            "type": "closing_sequence_final_picks",
            "date": state["date"],
            "picks": state["snapshot_picks"],
        })
    logger.info(f"[Closing Sequence] 3:38 PM BROADCAST: {len(state['snapshot_picks'])} finalized pick(s) pushed.")


def _step_lock(state: Dict[str, Any], lock_picks: Callable[[List[Dict[str, Any]]], Dict[str, Any]]) -> None:
    """`lock_picks` is app.py's existing full lock sequence (news enrichment -> lock_btst_picks
    -> VIX fetch -> per-strategy signal journal logging) — this module doesn't re-implement any
    of that, it just re-triggers it at 3:40 PM against the CAS-confirmed picks instead of
    duplicating that already-tested orchestration here."""
    picks = state["snapshot_picks"]
    result = lock_picks(picks)
    state["lock_result"] = result
    state["lock_done"] = True
    logger.info(f"[Closing Sequence] 3:40 PM LOCK complete: {result.get('locked_count', 0)} pick(s) locked into Signal Journal.")


def run_step_if_due(
    time_in_mins: int,
    today_date: str,
    get_current_stocks: Callable[[], List[Dict[str, Any]]],
    lock_picks: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
    broadcast: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[str]:
    """Runs whichever step is next due, if any (at most one step per call — the scheduler's
    own tick cadence naturally calls this often enough to catch up quickly). Returns a short
    label of what ran, or None if nothing was due this tick.

    `broadcast`, if supplied, is called after EVERY step (not just the dedicated 3:38 PM
    BROADCAST step) with a lightweight progress event — a connected dashboard can show the
    pipeline advancing through snapshot -> cas_close -> scoring -> broadcast -> lock in real
    time, not just receive the one final push. The 3:38 PM step additionally sends the richer
    "closing_sequence_final_picks" event with the full picks payload — see _step_broadcast."""
    if is_trading_holiday(today_date):
        return None

    state = _load_state(today_date)

    def _notify(step: str):
        if broadcast is not None:
            broadcast({"type": "closing_sequence_progress", "step": step, "date": today_date})

    if not state["snapshot_done"] and time_in_mins >= SNAPSHOT_MINS:
        _step_snapshot(state, get_current_stocks)
        _save_state(state)
        _notify("snapshot")
        return "snapshot"

    if state["snapshot_done"] and not state.get("auto_lock_25_done") and time_in_mins >= AUTO_LOCK_PICKS_MINS:
        state["auto_lock_25_done"] = True
        if lock_picks is not None and state.get("snapshot_picks"):
            try:
                lock_picks(state["snapshot_picks"])
            except Exception as ex:
                logger.warning(f"[Closing Sequence] 3:25 PM provisional lock callback error: {ex}")
        _save_state(state)
        if broadcast is not None:
            broadcast({"type": "auto_lock_325_picks", "date": today_date, "status": "LOCKED_325", "picks": state.get("snapshot_picks", [])})
        logger.info(f"[Closing Sequence] 3:25:00 PM IST: AUTO-LOCK 3:25 PM BTST PICKS complete ({len(state.get('snapshot_picks', []))} picks).")
        return "auto_lock_325"

    if state.get("auto_lock_25_done") and not state.get("final_bell_30_done") and time_in_mins >= FINAL_BELL_LOCK_MINS:
        state["final_bell_30_done"] = True
        state["btst_status"] = "confirmed"
        if lock_picks is not None and state.get("snapshot_picks"):
            try:
                lock_picks(state["snapshot_picks"])
            except Exception as ex:
                logger.warning(f"[Closing Sequence] 3:30 PM market lock callback error: {ex}")
        _save_state(state)
        if broadcast is not None:
            broadcast({"type": "market_lock", "btst_status": "confirmed", "date": today_date})
        logger.info("[Closing Sequence] 3:30:00 PM IST: FINAL CONFIRMED MARKET BELL LOCK complete.")
        return "market_lock_330"

    if state.get("final_bell_30_done") and not state["cas_close_done"] and time_in_mins >= CAS_CLOSE_MINS:
        _step_cas_close(state)
        _save_state(state)
        _notify("cas_close")
        return "cas_close"

    if state["cas_close_done"] and not state["scoring_done"] and time_in_mins >= SCORING_MINS:
        _step_scoring(state)
        _save_state(state)
        _notify("scoring")
        return "scoring"

    if state["scoring_done"] and not state["broadcast_done"] and time_in_mins >= BROADCAST_MINS:
        _step_broadcast(state, broadcast)
        _save_state(state)
        _notify("broadcast")
        return "broadcast"

    if state["broadcast_done"] and not state["lock_done"] and time_in_mins >= LOCK_MINS:
        _step_lock(state, lock_picks)
        _save_state(state)
        _notify("lock")
        return "lock"

    return None
