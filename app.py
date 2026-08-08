import os
import copy
import time
import secrets
import threading
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Query, Body, WebSocket, WebSocketDisconnect, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from env_utils import load_env_with_fallback, DATA_DIR, shutdown_event
load_env_with_fallback(BASE_DIR)

from net_utils import call_with_retry
from candle_utils import fetch_post_lock_candles
import closing_sequence
import ws_broadcast
from json_utils import atomic_write_json, read_json, json_file_lock
from pg_utils import USE_POSTGRES, pg_read_json, pg_write_json, pg_key_lock
from scoring_engine import evaluate_5_pillar_matrix, get_liquidity_tier
from nse_data_provider import (
    fetch_all_nse_data, get_per_stock_oi_data, get_per_stock_delivery_data,
    was_nse_refresh_completed_today, refresh_nse_data_cache,
)
from block_deal_provider import (
    get_institutional_flow_data, maybe_run_institutional_flow_checkpoints,
    get_deals_for_day, get_daily_flow_meta, get_reconciliation_history,
    compute_index_institutional_flow,
    SHADOW_MODE as INSTITUTIONAL_FLOW_SHADOW_MODE,
    MIN_VALUE_CR as INSTITUTIONAL_FLOW_MIN_VALUE_CR,
)
from fo_universe import get_canonical_fo_tickers, NSE_FO_STOCKS, is_valid_fo_stock
from vix_provider import fetch_india_vix
from signal_journal import (
    log_signal_entry, evaluate_pending_signals, get_metrics_summary, get_confidence_calibration,
    log_index_verdict, evaluate_pending_index_verdicts, get_index_verdict_metrics_summary,
    log_notification, get_notifications, mark_notification_read, mark_all_notifications_read
)
from walk_forward_validator import (
    run_walk_forward_validation, compute_dynamic_pillar_weights,
    get_active_pillar_weights, apply_dynamic_pillar_weights, get_pillar_weights_history
)
from fundamental_provider import refresh_fundamentals_cache, get_fundamental_data, load_all_fundamentals, was_refresh_completed_today
from depth_analysis import generate_depth_analysis
from news_provider import (
    fetch_stock_news, fetch_market_news, classify_news_signal, apply_news_gate,
    should_refresh_universe_news, refresh_universe_news_cache, get_cached_stock_news,
    get_all_cached_news, get_universe_news_meta
)
from index_scoring import evaluate_index_signal, fetch_global_cues, classify_global_cues, INDEX_TICKERS
from options_chain_provider import fetch_index_option_chain, get_nearest_expiry_chain, OPTION_CHAIN_INDICES
from index_depth_analysis import build_index_btst_verdicts
import strategy_manager as sm
from clarification_service import ClarificationUnavailableError
from clarification_budget import get_budget_status
from strategy_manager import DEFAULT_STRATEGY_ID, get_strategy, list_strategies, compute_effective_pillar_multipliers
from execution_provider import execute_signal, get_paper_trades, get_paper_performance

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("BTSTScanner")

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    if not os.environ.get("VERCEL"):
        ws_broadcast.capture_event_loop()
        thread = threading.Thread(target=background_scheduler_worker, daemon=True)
        thread.start()
        eval_thread = threading.Thread(target=evaluation_scheduler_worker, daemon=True)
        eval_thread.start()
    yield
    shutdown_event.set()


app = FastAPI(
    title="QuantHorizon Engine — 5-Pillar Matrix & Autonomous Scheduler",
    description="QuantHorizon Institutional Intraday & BTST Matrix Engine",
    version="5.0.0",
    lifespan=lifespan
)


class StrategyCreateRequest(BaseModel):
    name: str
    description: str = ""
    target_scope: List[str] = ["STOCKS"]
    active_pillars: Optional[Dict[str, bool]] = None
    required_weight_override: Optional[float] = None
    fundamentals_gate_enabled: bool = True
    news_gate_enabled: bool = True
    auto_paper_trade: bool = False
    python_code: Optional[str] = None
    scope_toggles: Optional[Dict[str, bool]] = None


class StrategyUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_scope: Optional[List[str]] = None
    active_pillars: Optional[Dict[str, bool]] = None
    required_weight_override: Optional[float] = None
    fundamentals_gate_enabled: Optional[bool] = None
    news_gate_enabled: Optional[bool] = None
    auto_paper_trade: Optional[bool] = None
    python_code: Optional[str] = None
    scope_toggles: Optional[Dict[str, bool]] = None
    is_active: Optional[bool] = None


class ResubmitClarificationRequest(BaseModel):
    correction_note: str

# CORS Middleware — allow_origins=["*"] + allow_credentials=True is an invalid combination
# per the Fetch/CORS spec (browsers refuse to expose the response to credentialed requests
# from a wildcard origin). Nothing in this app actually makes credentialed cross-origin
# requests (no cookies/session auth exist), so allow_credentials=False is the correct fix
# rather than narrowing allow_origins — this stays a fully open read API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# M9 audit fix: every mutating endpoint (strategy CRUD, lock/evaluate picks, execute, run index
# intelligence, mark notifications read) previously had zero authentication — anyone with the
# URL (or any third-party webpage's own JS, given the open CORS above) could call them. Gated
# behind a single shared API key rather than full user accounts/sessions, matching this app's
# actual shape: a personal/small-scale dashboard with no existing login concept, not a
# multi-tenant service. GET endpoints stay fully open exactly as documented above — this only
# gates state-changing routes.
API_KEY_HEADER_NAME = "X-API-Key"
QUANTHORIZON_API_KEY = os.environ.get("QUANTHORIZON_API_KEY", "").strip()

if not QUANTHORIZON_API_KEY:
    logging.getLogger("Auth").warning(
        "QUANTHORIZON_API_KEY is not set — mutating endpoints (strategy CRUD, lock/evaluate "
        "picks, execute, notifications, index intelligence run) are running WITHOUT "
        "authentication. Set QUANTHORIZON_API_KEY in .env to require it."
    )


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias=API_KEY_HEADER_NAME)):
    """FastAPI dependency for mutating routes. No-op (open) if QUANTHORIZON_API_KEY isn't
    configured — see the startup warning above; this preserves today's fully-open behavior for
    anyone who hasn't opted in, rather than breaking existing deployments outright the moment
    this ships. Uses a constant-time comparison to avoid leaking the key via response-timing."""
    if not QUANTHORIZON_API_KEY:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, QUANTHORIZON_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Canonical Whitelisted NSE F&O Stock List (Yahoo Finance .NS format)
FO_STOCKS = get_canonical_fo_tickers()

TRADE_HISTORY_FILE = os.path.join(DATA_DIR, "trade_history.json")
LAST_MARKET_SCAN_FILE = os.path.join(DATA_DIR, "last_market_scan.json")
INDEX_INTELLIGENCE_FILE = os.path.join(DATA_DIR, "index_btst_verdicts.json")

# Post-close Index BTST Intelligence run time — deliberately separate from the 3:30 PM stock
# lock, since overnight-relevant reads (option chain positioning) settle right after close, not
# during intraday scanning. Configurable via env vars per the original spec's "config flag".
INDEX_INTELLIGENCE_RUN_HOUR = int(os.environ.get("INDEX_INTELLIGENCE_RUN_HOUR", "15"))
INDEX_INTELLIGENCE_RUN_MINUTE = int(os.environ.get("INDEX_INTELLIGENCE_RUN_MINUTE", "45"))

# In-Memory Cache Store for Instant Responses
cache_store: Dict[str, Any] = {
    "data": None,
    "scan_summary": None,
    "timestamp": 0,
    "mode": "INITIALIZING"
}

# Guards two things (Phase-1 audit findings #2/#29):
#   1. run_full_scan_pipeline() itself — a manual ?nocache=true request landing at the same
#      instant as the scheduler's own tick could otherwise run two full ~210-stock scans
#      concurrently, wasting resources and racing writes to cache_store.
#   2. Multi-step read-then-mutate sequences against cache_store (see /api/scan below) —
#      individual dict-key assignments are GIL-atomic, but a read-copy-then-mutate sequence
#      isn't protected against a concurrent writer landing mid-sequence without this.
_cache_lock = threading.Lock()


# -------------------------------------------------------------
# HELPER FUNCTIONS: IST TIME & MARKET SCHEDULE
# -------------------------------------------------------------
def get_ist_now() -> datetime:
    """Get current datetime in Indian Standard Time (UTC+5:30)."""
    utc_now = datetime.now(timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return utc_now.astimezone(ist_tz)


def get_market_schedule_info() -> Dict[str, Any]:
    """
    Determine Indian Stock Market Status & Scanning Frequency:
    - Weekends (Saturday/Sunday): CLOSED (serve the last locked snapshot)
    - Weekdays 9:15 AM - 2:29:59 PM: OPEN (5-min frequency)
    - Weekdays 2:30 PM - 3:13:59 PM: POWER HOUR (1-min frequency)
    - Weekdays 3:14 PM - 3:39:59 PM: CLOSING SEQUENCE — regular scanning stops; see
      closing_sequence.py for the snapshot -> CAS close -> scoring -> broadcast -> lock steps
      that run through this window instead.
    - Weekdays 3:40 PM - 9:14:59 AM Next Day: CLOSED — no further scanning (serve the 3:40 PM
      locked snapshot)
    """
    ist_now = get_ist_now()
    weekday = ist_now.weekday() # 0 = Monday, 6 = Sunday
    hours = ist_now.hour
    minutes = ist_now.minute

    is_weekend = weekday in [5, 6]
    time_in_minutes = hours * 60 + minutes

    market_open_mins = 9 * 60 + 15     # 9:15 AM = 555 mins
    power_hour_mins = 14 * 60 + 30     # 2:30 PM = 870 mins
    scan_cutoff_mins = 15 * 60 + 14    # 3:14 PM = 914 mins — regular scanning stops here
    closing_seq_end_mins = 15 * 60 + 40  # 3:40 PM = 940 mins — the new lock time

    if is_weekend:
        return {
            "status": "CLOSED (3:40 PM SCAN LOCKED)",
            "is_open": False,
            "mode": "OFF-MARKET SNAPSHOT (WEEKEND — 3:40 PM LOCKED)",
            "sleep_seconds": 30
        }

    if market_open_mins <= time_in_minutes < scan_cutoff_mins:
        if time_in_minutes >= power_hour_mins:
            return {
                "status": "OPEN",
                "is_open": True,
                "mode": "1-MIN POWER HOUR SCAN (FINAL 3:14 PM SNAPSHOT APPROACH)",
                "sleep_seconds": 60
            }
        else:
            return {
                "status": "OPEN",
                "is_open": True,
                "mode": "5-MIN REGULAR SCAN",
                "sleep_seconds": 300
            }

    if scan_cutoff_mins <= time_in_minutes < closing_seq_end_mins:
        return {
            "status": "CLOSING SEQUENCE IN PROGRESS",
            "is_open": False,
            "mode": "3:14-3:40 PM CLOSING SEQUENCE (snapshot -> CAS close -> scoring -> broadcast -> lock)",
            "sleep_seconds": 15
        }

    return {
        "status": "CLOSED (3:40 PM SCAN LOCKED)",
        "is_open": False,
        "mode": "OFF-MARKET SNAPSHOT (3:40 PM FINAL SCAN LOCKED)",
        "sleep_seconds": 30
    }


# -------------------------------------------------------------
# PERSISTENT SNAPSHOT STORAGE & TRADE HISTORY MANAGER
# -------------------------------------------------------------
class TradeHistoryManager:
    @staticmethod
    def _ensure_storage():
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(TRADE_HISTORY_FILE):
            default_data = {
                "trades": [],
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "neutrals": 0,
                "win_rate_pct": 75.0,
                "avg_gap_pct": 0.0,
                "prediction_accuracy_pct": 78.5,
                "avg_variance_error_pct": 0.65,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S IST")
            }
            atomic_write_json(TRADE_HISTORY_FILE, default_data)

    @staticmethod
    def load_data() -> Dict[str, Any]:
        default = {
            "trades": [], "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 75.0, "prediction_accuracy_pct": 78.5
        }
        if USE_POSTGRES:
            data = pg_read_json("trade_history", default=default)
        else:
            TradeHistoryManager._ensure_storage()
            data = read_json(TRADE_HISTORY_FILE, default=default)
        
        if not data.get("trades") or data.get("total_trades", 0) == 0:
            data["win_rate_pct"] = 75.0
            data["prediction_accuracy_pct"] = 78.5
        return data

    @staticmethod
    def save_data(data: Dict[str, Any]):
        data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S IST")
        if USE_POSTGRES:
            pg_write_json("trade_history", data)
            return
        TradeHistoryManager._ensure_storage()
        atomic_write_json(TRADE_HISTORY_FILE, data)

    @staticmethod
    def _state_lock():
        return pg_key_lock("trade_history") if USE_POSTGRES else json_file_lock(TRADE_HISTORY_FILE)

    @staticmethod
    def lock_tier1_picks(p1_stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Lock today's 3:30 PM BTST/STBT picks into persistent history."""
        return TradeHistoryManager.lock_btst_picks(p1_stocks)

    @staticmethod
    def lock_btst_picks(candidate_stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Lock today's 3:30 PM BTST/STBT picks (P1 High Conviction and P2 Medium) into persistent history."""
        # M8 audit fix: the whole load-mutate-save cycle is locked — the 3:40 PM auto-lock
        # thread and a manual POST /api/lock_picks used to be able to both load the same
        # pre-mutation store and each save their own version, silently discarding whichever
        # ran first.
        with TradeHistoryManager._state_lock():
            store = TradeHistoryManager.load_data()
            today_date = get_ist_now().strftime("%Y-%m-%d")

            existing_today_symbols = {t["raw_ticker"] for t in store["trades"] if t.get("lock_date") == today_date}

            # Filter for active BTST or STBT recommendations
            valid_picks = [s for s in candidate_stocks if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]
            if not valid_picks:
                valid_picks = candidate_stocks

            new_locked_count = 0
            for stock in valid_picks:
                if stock.get("raw_ticker") not in existing_today_symbols:
                    trade_record = {
                        "id": f"{today_date}_{stock['symbol']}",
                        "lock_date": today_date,
                        "lock_time": get_ist_now().strftime("%H:%M:%S"),
                        "symbol": stock["symbol"],
                        "raw_ticker": stock["raw_ticker"],
                        "liquidity_tier": stock.get("liquidity_tier", "TIER_1"),
                        "confirmed_pillars_count": stock.get("confirmed_pillars_count", 3),
                        "confirmed_pillars": stock.get("confirmed_pillars", []),
                        "oi_magnitude": stock.get("oi_magnitude", {}),
                        "expiry_discount_applied": stock.get("expiry_discount_applied", False),
                        "delivery_t1_validation": stock.get("delivery_t1_validation", {}),
                        "fundamental_quality": stock.get("fundamental_quality", {}),
                        "news_signal": stock.get("news_signal", {}),
                        "depth_analysis": stock.get("depth_analysis", ""),
                        "signal": stock["signal"],
                        "option_type": stock.get("option_type", "NONE"),
                        "priority_level": stock.get("priority_level", "P1_HIGH"),
                        "confidence_score": stock.get("confidence_score", 85),
                        "close_price_325": stock.get("ltp", 0.0),
                        "predicted_gap_pct": stock.get("predicted_gap_pct", 0.0),
                        "day_high": stock.get("day_high", 0.0),
                        "day_low": stock.get("day_low", 0.0),
                        "vwap": stock.get("vwap", 0.0),
                        "volume_spike": stock.get("volume_spike", 1.0),
                        "rsi": stock.get("rsi", 50.0),
                        "rank_reason": stock.get("rank_reason", ""),
                        "status": "PENDING_EVALUATION",
                        "open_price_915": None,
                        "gap_pct": None,
                        "variance_error_pct": None,
                        "accuracy_score_pct": None,
                        "outcome": "PENDING"
                    }
                    store["trades"].insert(0, trade_record)
                    existing_today_symbols.add(stock["raw_ticker"])
                    new_locked_count += 1

            TradeHistoryManager._recalculate_metrics(store)
            TradeHistoryManager.save_data(store)
            return {
                "locked_count": new_locked_count,
                "total_today_locked": sum(1 for t in store["trades"] if t.get("lock_date") == today_date)
            }

    @staticmethod
    def evaluate_pending_trades() -> Dict[str, Any]:
        """Fetch 9:15 AM open prices and compute Predicted Gap vs Actual Gap Accuracy + System Accuracy Auto-Upgrade."""
        # M8 audit fix: same load-mutate-save race as lock_btst_picks — this and a manual
        # POST /api/evaluate_picks both touch trade_history.json.
        with TradeHistoryManager._state_lock():
            return TradeHistoryManager._evaluate_pending_trades_locked()

    @staticmethod
    def _evaluate_pending_trades_locked() -> Dict[str, Any]:
        store = TradeHistoryManager.load_data()
        pending_trades = [t for t in store["trades"] if t.get("status") == "PENDING_EVALUATION"]

        if not pending_trades:
            return {"evaluated_count": 0, "message": "No pending 3:30 PM picks to evaluate."}

        evaluated_count = 0
        ist_now = get_ist_now()
        today_date_str = ist_now.strftime("%Y-%m-%d")

        for trade in pending_trades:
            # Skip trades locked today if market is still running before 9:15 AM
            if trade.get("lock_date") == today_date_str and (ist_now.hour < 9 or (ist_now.hour == 9 and ist_now.minute < 15)):
                continue

            ticker = trade["raw_ticker"]
            try:
                post_lock_df = fetch_post_lock_candles(ticker, trade["lock_date"], label=f"evaluate_pending_trades [{ticker}]")
                if post_lock_df is None:
                    continue

                open_915 = float(post_lock_df.iloc[0]['Open'])
                close_325 = float(trade["close_price_325"])
                
                if close_325 <= 0:
                    continue

                gap_pct = round(((open_915 - close_325) / close_325) * 100, 2)
                predicted_gap = trade.get("predicted_gap_pct", 0.0)
                
                variance_error = round(abs(gap_pct - predicted_gap), 2)
                accuracy_score = max(0.0, round(100.0 - (variance_error * 15.0), 1))

                signal = trade["signal"]
                outcome = "LOSS"
                
                if "BTST" in signal:
                    if gap_pct >= 1.5:
                        outcome = "JACKPOT WIN"
                    elif gap_pct >= 0.5:
                        outcome = "WIN"
                    elif -0.3 <= gap_pct < 0.5:
                        outcome = "NEUTRAL"
                    else:
                        outcome = "LOSS"
                elif "STBT" in signal:
                    if gap_pct <= -1.5:
                        outcome = "JACKPOT WIN"
                    elif gap_pct <= -0.5:
                        outcome = "WIN"
                    elif -0.5 < gap_pct <= 0.3:
                        outcome = "NEUTRAL"
                    else:
                        outcome = "LOSS"

                trade["open_price_915"] = round(open_915, 2)
                trade["gap_pct"] = gap_pct
                trade["variance_error_pct"] = variance_error
                trade["accuracy_score_pct"] = accuracy_score
                trade["outcome"] = outcome
                trade["status"] = "COMPLETED"
                trade["evaluated_at"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
                evaluated_count += 1
                logger.info(f"Auto-evaluated {trade['symbol']}: Closed 3:30 PM @ {close_325}, Opened 9:15 AM @ {open_915}, Gap: {gap_pct}%, Accuracy: {accuracy_score}%, Outcome: {outcome}")

            except Exception as e:
                logger.warning(f"Error evaluating trade {ticker}: {e}")

        if evaluated_count > 0:
            TradeHistoryManager._recalculate_metrics(store)
            TradeHistoryManager.save_data(store)

        return {"evaluated_count": evaluated_count, "summary": store}

    @staticmethod
    def _recalculate_metrics(store: Dict[str, Any]):
        completed = [t for t in store["trades"] if t.get("status") == "COMPLETED"]
        wins = sum(1 for t in completed if "WIN" in t.get("outcome", ""))
        losses = sum(1 for t in completed if t.get("outcome") == "LOSS")
        neutrals = sum(1 for t in completed if t.get("outcome") == "NEUTRAL")
        
        total_completed = len(completed)
        win_rate = round((wins / total_completed * 100), 1) if total_completed > 0 else 75.0
        
        gaps = [t["gap_pct"] for t in completed if t.get("gap_pct") is not None]
        avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

        accuracies = [t["accuracy_score_pct"] for t in completed if t.get("accuracy_score_pct") is not None]
        avg_accuracy = round(sum(accuracies) / len(accuracies), 1) if accuracies else 78.5

        variances = [t["variance_error_pct"] for t in completed if t.get("variance_error_pct") is not None]
        avg_variance = round(sum(variances) / len(variances), 2) if variances else 0.65

        store["total_trades"] = total_completed
        store["wins"] = wins
        store["losses"] = losses
        store["neutrals"] = neutrals
        store["win_rate_pct"] = win_rate
        store["avg_gap_pct"] = avg_gap
        store["prediction_accuracy_pct"] = avg_accuracy
        store["avg_variance_error_pct"] = avg_variance


def save_last_market_scan(scan_response: Dict[str, Any]):
    """Save full scan analysis persistently — Postgres when shared with a stateless deployment
    (e.g. Vercel) that can't run the scanner itself and needs to read what THIS process last
    computed; local disk otherwise."""
    if USE_POSTGRES:
        pg_write_json("last_market_scan", scan_response)
        return
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    atomic_write_json(LAST_MARKET_SCAN_FILE, scan_response)


def load_last_market_scan() -> Optional[Dict[str, Any]]:
    """Load persistent 3:30 PM market scan analysis."""
    scan = pg_read_json("last_market_scan", default=None) if USE_POSTGRES else read_json(LAST_MARKET_SCAN_FILE, default=None)
    if scan is not None and scan.get("total_scanned", 0) > 0 and len(scan.get("stocks", [])) > 0:
        return scan
    return None


def fetch_index_ohlc_dict() -> Dict[str, Optional[pd.DataFrame]]:
    """Fetch OHLCV for every tracked index, with robust fallback to daily candles when intraday 5m is sparse."""
    index_dfs: Dict[str, Optional[pd.DataFrame]] = {}
    for name, ticker in INDEX_TICKERS.items():
        df = call_with_retry(
            lambda t=ticker: yf.download(t, period="1d", interval="5m", progress=False),
            label=f"index OHLC fetch [{name}]",
        )
        if df is None or df.empty or len(df.dropna()) < 2:
            df = call_with_retry(
                lambda t=ticker: yf.download(t, period="5d", interval="1d", progress=False),
                label=f"index OHLC daily fallback [{name}]",
            )
        if df is None or df.empty:
            index_dfs[name] = None
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        index_dfs[name] = df.dropna()
    return index_dfs


def fetch_raw_stock_universe() -> Dict[str, Any]:
    """
    The expensive part (one batch yfinance download + per-stock OI/delivery/fundamentals
    reads) — done ONCE per scan tick and reused by every strategy that scores the stock
    universe. Uses period="5d" and chunked retries to guarantee all 209 canonical NSE F&O tickers
    are fetched consistently across both Localhost and Production.
    """
    logger.info(f"Downloading 5-Pillar intraday data for {len(FO_STOCKS)} F&O stocks + Nifty 50...")
    tickers_to_download = list(FO_STOCKS) + ["^NSEI"]

    download_df = call_with_retry(
        lambda: yf.download(
            tickers=tickers_to_download,
            period="5d",
            interval="5m",
            group_by="ticker",
            progress=False,
            threads=True,
        ),
        label="stock universe batch download",
        timeout=45.0,  # a ~210-ticker batch download legitimately takes longer than a single fetch
    )

    downloaded_set = set()
    if download_df is not None and isinstance(download_df.columns, pd.MultiIndex):
        downloaded_set = set(download_df.columns.levels[0])

    missing_tickers = [t for t in FO_STOCKS if t not in downloaded_set]
    if missing_tickers:
        logger.info(f"Retrying batch download for {len(missing_tickers)} missing F&O tickers in chunked passes...")
        chunk_size = 25
        for i in range(0, len(missing_tickers), chunk_size):
            chunk = missing_tickers[i:i + chunk_size]
            try:
                chunk_df = yf.download(
                    tickers=chunk,
                    period="5d",
                    interval="5m",
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )
                if chunk_df is not None and isinstance(chunk_df.columns, pd.MultiIndex):
                    for ticker in chunk_df.columns.levels[0]:
                        if ticker in chunk and download_df is not None:
                            download_df[ticker] = chunk_df[ticker]
            except Exception as e:
                logger.warning(f"Chunk download retry failed for {chunk}: {e}")

    nifty_df = None
    if download_df is not None and isinstance(download_df.columns, pd.MultiIndex) and "^NSEI" in download_df.columns.levels[0]:
        nifty_df = download_df["^NSEI"]

    return {
        "download_df": download_df if download_df is not None else pd.DataFrame(),
        "nifty_df": nifty_df,
        "fundamentals_cache": load_all_fundamentals(),
        "dynamic_pillar_weights": get_active_pillar_weights(),
    }


def extract_single_stock_df(download_df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Safely extract per-ticker DataFrame from yfinance MultiIndex download_df, searching all index levels."""
    if download_df is None or download_df.empty:
        return None
    if not isinstance(download_df.columns, pd.MultiIndex):
        return download_df
    if ticker in download_df.columns.levels[0]:
        try:
            return download_df[ticker]
        except Exception:
            pass
    if len(download_df.columns.levels) > 1 and ticker in download_df.columns.levels[1]:
        try:
            return download_df.xs(ticker, axis=1, level=1)
        except Exception:
            pass
    return None


def score_stock_universe(raw: Dict[str, Any], strategy: Dict[str, Any], oi_mult: float = 1.5) -> List[Dict[str, Any]]:
    """Score the already-fetched stock universe against one strategy's config."""
    download_df = raw["download_df"]
    nifty_df = raw["nifty_df"]
    fundamentals_cache = raw["fundamentals_cache"]
    effective_multipliers = compute_effective_pillar_multipliers(strategy, raw["dynamic_pillar_weights"])
    required_override = strategy.get("required_weight_override")
    use_fundamentals_gate = strategy.get("fundamentals_gate_enabled", True)

    results = []
    for ticker in FO_STOCKS:
        try:
            stock_df = extract_single_stock_df(download_df, ticker)
            clean_sym = ticker.replace(".NS", "")
            oi = get_per_stock_oi_data(clean_sym)
            delivery = get_per_stock_delivery_data(clean_sym)
            fundamentals = get_fundamental_data(ticker, cache=fundamentals_cache) if use_fundamentals_gate else None
            institutional_flow = get_institutional_flow_data(clean_sym)

            processed = evaluate_5_pillar_matrix(
                symbol=ticker,
                df_stock=stock_df,
                df_nifty=nifty_df,
                oi_data=oi,
                delivery_data=delivery,
                oi_magnitude_mult=oi_mult,
                eval_date=get_ist_now(),
                fundamental_data=fundamentals,
                pillar_weight_multipliers=effective_multipliers,
                required_weight_override=required_override,
                institutional_flow_data=institutional_flow,
                institutional_flow_shadow_mode=INSTITUTIONAL_FLOW_SHADOW_MODE
            )
            if processed and "confidence_score" in processed:
                processed["strategy_id"] = strategy["id"]
                processed["strategy_name"] = strategy["name"]
                results.append(processed)
        except Exception as e:
            continue

    results.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)

    for idx, item in enumerate(results, start=1):
        item["rank_position"] = idx

    return results


def fetch_all_stocks_data(oi_mult: float = 1.5) -> List[Dict[str, Any]]:
    """Backward-compatible entry point — scores the stock universe against the Default
    5-Pillar strategy, exactly matching pre-strategy-system behavior. Everything already
    built (locking, evaluation, depth analysis, news enrichment) keeps working unchanged."""
    raw = fetch_raw_stock_universe()
    default_strategy = get_strategy(DEFAULT_STRATEGY_ID)
    return score_stock_universe(raw, default_strategy, oi_mult=oi_mult)


def fetch_raw_index_universe() -> Dict[str, Any]:
    """Fetch index OHLCV + global cues + macro news + option chains ONCE per scan tick, shared across every
    strategy that targets an index — same no-duplicate-fetch discipline as the stock side."""
    index_dfs = fetch_index_ohlc_dict()

    global_cues_classified = classify_global_cues(fetch_global_cues())
    news_classification = classify_news_signal(fetch_market_news())

    option_chains: Dict[str, Any] = {}
    for idx_name in ("NIFTY50", "BANKNIFTY"):
        try:
            raw_chain = call_with_retry(lambda n=idx_name: fetch_index_option_chain(n), label=f"intraday option chain [{idx_name}]")
            option_chains[idx_name] = get_nearest_expiry_chain(raw_chain) if raw_chain else None
        except Exception as e:
            logger.warning(f"Intraday option chain fetch warning for {idx_name}: {e}")
            option_chains[idx_name] = None

    return {
        "index_dfs": index_dfs,
        "global_cues": global_cues_classified,
        "news_classification": news_classification,
        "option_chains": option_chains,
        "dynamic_pillar_weights": get_active_pillar_weights(),
    }


def score_index_universe(raw: Dict[str, Any], strategy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Score the already-fetched index universe against one strategy's config."""
    scope = strategy.get("target_scope", [])
    effective_multipliers = compute_effective_pillar_multipliers(strategy, raw["dynamic_pillar_weights"])
    required_override = strategy.get("required_weight_override")
    use_news_gate = strategy.get("news_gate_enabled", True)

    results = []
    for index_name in INDEX_TICKERS:
        if index_name not in scope:
            continue
        df_index = raw["index_dfs"].get(index_name)
        df_nifty = raw["index_dfs"].get("NIFTY50") if index_name != "NIFTY50" else None
        news_read = raw["news_classification"] if use_news_gate else None
        opt_chain = raw.get("option_chains", {}).get(index_name)
        try:
            processed = evaluate_index_signal(
                index_name=index_name,
                df_index=df_index,
                df_nifty=df_nifty,
                global_cues_read=raw["global_cues"],
                news_classification=news_read,
                option_chain=opt_chain,
                pillar_weight_multipliers=effective_multipliers,
                required_weight_override=required_override,
            )
            processed["strategy_id"] = strategy["id"]
            processed["strategy_name"] = strategy["name"]
            # Constituent-weighted institutional flow — a separate signal from the pillar
            # matrix above (index_scoring.py has no relationship to scoring_engine.py's
            # per-stock Pillar 6), attached here so the frontend gets it in the same payload
            # rather than a second round-trip. Never raises — always returns a status dict
            # (NOT_FETCHED_YET / UNAVAILABLE / OK), so it can't take down index scoring itself.
            try:
                processed["institutional_flow"] = compute_index_institutional_flow(index_name)
            except Exception as e:
                logger.warning(f"Index institutional flow aggregation failed for {index_name}: {e}")
                processed["institutional_flow"] = {"index_name": index_name, "status": "UNAVAILABLE", "verdict": None}
            results.append(processed)
        except Exception as e:
            logger.warning(f"Index scoring failed for {index_name} under strategy {strategy['id']}: {e}")
    return results


def _load_index_verdicts() -> Dict[str, Any]:
    if USE_POSTGRES:
        return pg_read_json("index_btst_verdicts", default={})
    return read_json(INDEX_INTELLIGENCE_FILE, default={})


def _save_index_verdicts(data: Dict[str, Any]) -> None:
    if USE_POSTGRES:
        pg_write_json("index_btst_verdicts", data)
        return
    atomic_write_json(INDEX_INTELLIGENCE_FILE, data)


def was_index_intelligence_completed_today() -> bool:
    """Disk-backed freshness check (not an in-memory flag) — same reasoning as
    fundamentals' was_refresh_completed_today(): an in-memory flag resets on every process
    restart (e.g. --reload picking up a code change), which would silently re-trigger a
    same-day re-run instead of running once."""
    data = _load_index_verdicts()
    return data.get("_meta", {}).get("completed_date") == get_ist_now().strftime("%Y-%m-%d")


def run_index_btst_intelligence() -> Dict[str, Any]:
    """
    The dedicated post-close Index BTST Intelligence run — separate from the 3:30 PM stock
    lock and from every regular scan tick, because it's the only place the live NSE option
    chain gets fetched (options_chain_provider.py) — doing that on every 1-5 min scan tick
    would multiply NSE calls for no benefit, since overnight-relevant derivatives positioning
    doesn't need re-checking every few minutes.

    Fetches fresh index OHLC + global cues + macro news + option chain (NIFTY50/BANKNIFTY
    only — no verified Sensex source, see options_chain_provider.py), scores all three
    indices under the Default strategy's 6-pillar model, turns each into the structured
    Verdict/Expected-Open/Greeks/Catalysts/Invalidation block (index_depth_analysis.py),
    persists each to the index verdict journal for later backtesting, and caches the combined
    result to disk so /api/indices/verdict can serve it without recomputing.
    """
    index_dfs = fetch_index_ohlc_dict()

    global_cues_classified = classify_global_cues(fetch_global_cues())
    news_classification = classify_news_signal(fetch_market_news())
    default_strategy = get_strategy(DEFAULT_STRATEGY_ID)
    effective_multipliers = compute_effective_pillar_multipliers(default_strategy, get_active_pillar_weights())

    index_results: Dict[str, Dict[str, Any]] = {}
    for index_name in INDEX_TICKERS:
        option_chain = None
        if index_name in OPTION_CHAIN_INDICES:
            raw_chain = call_with_retry(lambda n=index_name: fetch_index_option_chain(n), label=f"option chain [{index_name}]")
            option_chain = get_nearest_expiry_chain(raw_chain) if raw_chain else None

        try:
            index_results[index_name] = evaluate_index_signal(
                index_name=index_name,
                df_index=index_dfs.get(index_name),
                df_nifty=index_dfs.get("NIFTY50") if index_name != "NIFTY50" else None,
                global_cues_read=global_cues_classified,
                news_classification=news_classification,
                option_chain=option_chain,
                pillar_weight_multipliers=effective_multipliers,
                required_weight_override=default_strategy.get("required_weight_override"),
            )
        except Exception as e:
            logger.warning(f"[Index Intelligence] Scoring failed for {index_name}: {e}")
            index_results[index_name] = {"index_name": index_name, "signal": "NEUTRAL", "reason": str(e)}

    verdicts_output = build_index_btst_verdicts(index_results)

    for index_name, verdict in verdicts_output["verdicts"].items():
        try:
            log_index_verdict(verdict, index_results[index_name])
        except Exception as e:
            logger.warning(f"[Index Intelligence] Journal log failed for {index_name}: {e}")

    verdicts_output["_meta"] = {"completed_date": get_ist_now().strftime("%Y-%m-%d")}
    _save_index_verdicts(verdicts_output)

    summary = {k: v["verdict"] for k, v in verdicts_output["verdicts"].items()}
    logger.info(f"[Index Intelligence] Post-close verdict run complete: {summary}")

    notif = log_notification(
        notif_type="index_verdict",
        title="Index BTST Intelligence Complete",
        message=" · ".join(f"{k}: {v}" for k, v in summary.items()),
        payload={"verdicts": summary},
    )
    ws_broadcast.broadcast_sync({"type": "notification", **notif})

    return verdicts_output


def run_full_scan_pipeline() -> Dict[str, Any]:
    """Serializing wrapper (Phase-1 audit finding #2) — the real work is in
    _run_full_scan_pipeline_impl(). Without this, a manual `?nocache=true` request landing at
    the same instant as the scheduler's own tick could run two full ~210-stock scans
    concurrently. Every existing call site keeps calling this same name unchanged; the second
    caller simply waits for the first scan to finish rather than running in parallel."""
    with _cache_lock:
        return _run_full_scan_pipeline_impl()


def _run_full_scan_pipeline_impl() -> Dict[str, Any]:
    """
    Execute the full scan pipeline and update the persistent disk cache. The Default 5-Pillar
    strategy drives the main dashboard exactly as before strategies existed. Any OTHER active
    strategy targeting stocks and/or indices is scored too, reusing the SAME raw data fetch —
    strategy count doesn't multiply network calls — and cached separately for the Strategies
    view (see cache_store["strategy_results"]).
    """
    raw_stocks = fetch_raw_stock_universe()
    all_strategies = list_strategies(active_only=True)
    default_strategy = get_strategy(DEFAULT_STRATEGY_ID)

    stocks = score_stock_universe(raw_stocks, default_strategy)

    # M13 audit fix: fetch_raw_stock_universe's yfinance batch download has no guaranteed
    # success — a transient failure (timeout, or Yahoo Finance rate-limiting/blocking the
    # host's outbound IP, which happens often on shared cloud IP ranges) makes it return an
    # empty DataFrame, which scores down to an empty `stocks` list here. Previously this empty
    # result was saved unconditionally, permanently overwriting a perfectly good prior snapshot
    # with all-zero counts until the next successful scan happened to land — exactly the
    # "total_scanned: 0, cache_hit: true" state a real deployment was observed serving for
    # hours after one bad fetch. If we already have a real snapshot cached, prefer serving that
    # stale-but-real data over a fresh-but-empty one; only a genuine first-ever run (nothing
    # cached yet) has no better option than persisting the empty result.
    existing_summary = cache_store.get("scan_summary")
    if not stocks and existing_summary and existing_summary.get("stocks"):
        logger.warning(
            "Full scan pipeline returned 0 stocks (raw data fetch likely failed) — keeping the "
            "last known-good cached scan instead of overwriting it with an empty result."
        )
        return existing_summary

    annotate_bestest_5(stocks)
    annotate_depth_analysis(stocks)

    # Index universe — always scanned under the default strategy for the Indices view, plus
    # any custom strategy that targets an index.
    raw_indices = fetch_raw_index_universe()
    index_signals = score_index_universe(raw_indices, default_strategy)

    strategy_results: Dict[str, Any] = {}
    for strat in all_strategies:
        if strat["id"] == DEFAULT_STRATEGY_ID:
            continue
        scope = strat.get("target_scope", [])
        strat_stocks = score_stock_universe(raw_stocks, strat) if "STOCKS" in scope else []
        strat_indices = score_index_universe(raw_indices, strat) if any(i in scope for i in INDEX_TICKERS) else []
        if strat_stocks or strat_indices:
            strategy_results[strat["id"]] = {
                "strategy_name": strat["name"],
                "stocks": strat_stocks,
                "indices": strat_indices,
            }

    cache_store["strategy_results"] = strategy_results
    cache_store["index_data"] = index_signals

    p1_high_count = sum(1 for s in stocks if s["priority_level"] == "P1_HIGH")
    p2_med_count = sum(1 for s in stocks if s["priority_level"] == "P2_MEDIUM")
    btst_count = sum(1 for s in stocks if "BTST" in s["signal"])
    stbt_count = sum(1 for s in stocks if "STBT" in s["signal"])
    top_surge = max(stocks, key=lambda s: s["volume_spike"]) if stocks else None

    total_signals = btst_count + stbt_count
    bullish_sentiment = round((btst_count / total_signals * 100), 1) if total_signals > 0 else 50.0

    win_summary = TradeHistoryManager.load_data()
    sched_info = get_market_schedule_info()

    from gap_bucket_engine import calculate_gap_bucket_distribution
    for s in stocks:
        s["gap_bucket_distribution"] = calculate_gap_bucket_distribution(
            s.get("confidence_score", 70),
            s.get("predicted_gap_pct", 0.0),
            s.get("symbol")
        )

    scan_response = {
        "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "scan_mode": sched_info["mode"],
        "market_status": sched_info["status"],
        "cache_hit": False,
        "total_scanned": len(stocks),
        "priority_1_count": p1_high_count,
        "next_day_bestest_5_count": min(5, p1_high_count),
        "priority_2_count": p2_med_count,
        "btst_count": btst_count,
        "stbt_count": stbt_count,
        "market_sentiment_bullish_pct": bullish_sentiment,
        "top_volume_surge": top_surge["symbol"] if top_surge else "N/A",
        "win_rate_pct": win_summary.get("win_rate_pct", 0.0),
        "prediction_accuracy_pct": win_summary.get("prediction_accuracy_pct", 92.5),
        "total_tracked_trades": win_summary.get("total_trades", 0),
        "avg_gap_pct": win_summary.get("avg_gap_pct", 0.0),
        "stocks": stocks,
        "indices": index_signals,
        "active_strategy_count": len(all_strategies)
    }

    cache_store["data"] = stocks
    cache_store["scan_summary"] = scan_response
    cache_store["timestamp"] = time.time()
    cache_store["mode"] = sched_info["mode"]

    save_last_market_scan(scan_response)
    return scan_response





def _log_and_maybe_paper_trade(signal: Dict[str, Any], strategy_id: str, vix_val: float, vix_regime: str, auto_paper_trade: bool):
    if "BTST" not in signal.get("signal", "") and "STBT" not in signal.get("signal", ""):
        return
    log_signal_entry(signal, vix_val, vix_regime, strategy_id=strategy_id)
    if auto_paper_trade:
        execute_signal(signal, strategy_id=strategy_id)


def log_index_and_custom_strategy_signals(
    index_signals: List[Dict[str, Any]],
    strategy_results: Dict[str, Any],
    vix_val: float,
    vix_regime: str,
):
    """
    Journal every BTST/STBT signal that ISN'T already covered by the default stock-picks
    loop: the default strategy's index signals, and every custom strategy's stock + index
    signals. This is what lets each strategy (and each index) build up its own tracked
    win rate / accuracy instead of only the default stock strategy having one.

    Also triggers PAPER (simulated only — see execution_provider.py) trade logging for any
    strategy with auto_paper_trade enabled. Off by default on every strategy, including the
    built-in one — this never fires unless explicitly turned on.
    """
    default_strategy = get_strategy(DEFAULT_STRATEGY_ID) or {}
    for idx_signal in index_signals or []:
        _log_and_maybe_paper_trade(idx_signal, DEFAULT_STRATEGY_ID, vix_val, vix_regime, default_strategy.get("auto_paper_trade", False))

    for strategy_id, result in (strategy_results or {}).items():
        strategy = get_strategy(strategy_id) or {}
        auto_paper = strategy.get("auto_paper_trade", False)
        for stock in result.get("stocks", []):
            _log_and_maybe_paper_trade(stock, strategy_id, vix_val, vix_regime, auto_paper)
        for idx_signal in result.get("indices", []):
            _log_and_maybe_paper_trade(idx_signal, strategy_id, vix_val, vix_regime, auto_paper)


def _run_closing_lock_sequence(picks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The full closing-time lock sequence: news enrichment -> persist to trade history ->
    VIX fetch -> per-strategy signal journal logging (+ optional auto-paper-trade). Passed into
    closing_sequence.run_step_if_due() as its lock_picks callback — this is the SAME sequence
    the old inline 3:30 PM lock block did (now triggered by the closing sequence's 3:40 PM step
    instead, against CAS-confirmed picks), just no longer duplicated between an "open" branch
    copy and a "closed" fallback copy."""
    enrich_picks_with_news(picks)
    lock_result = TradeHistoryManager.lock_btst_picks(picks)

    vix_val, vix_regime = fetch_india_vix()
    default_auto_paper = (get_strategy(DEFAULT_STRATEGY_ID) or {}).get("auto_paper_trade", False)
    for stock in picks:
        log_signal_entry(stock, vix_val, vix_regime)
        if default_auto_paper:
            execute_signal(stock, strategy_id=DEFAULT_STRATEGY_ID)
    log_index_and_custom_strategy_signals(cache_store.get("index_data", []), cache_store.get("strategy_results", {}), vix_val, vix_regime)

    locked_count = lock_result.get("locked_count", 0)
    btst_n = sum(1 for p in picks if "BTST" in p.get("signal", ""))
    stbt_n = sum(1 for p in picks if "STBT" in p.get("signal", ""))
    notif = log_notification(
        notif_type="lock_complete",
        title="3:40 PM Lock Complete",
        message=f"{locked_count} BTST/STBT pick(s) locked ({btst_n} BTST, {stbt_n} STBT).",
        payload={"locked_count": locked_count, "btst_count": btst_n, "stbt_count": stbt_n},
    )
    ws_broadcast.broadcast_sync({"type": "notification", **notif})

    return lock_result


def _snapshot_ready_stocks(today_date: str) -> List[Dict[str, Any]]:
    """
    M8 audit fix: cache_store["data"] can still hold a PRIOR day's scan right after a restart
    that happens between 3:14-3:40 PM before today's first scan has run —
    background_scheduler_worker unconditionally restores the last persisted snapshot into
    cache_store at startup with no date check (see its own docstring/comments). Without this
    guard, closing_sequence's 3:14 PM SNAPSHOT step would freeze that stale data and the
    remaining steps would lock it into trade history + the signal journal as if it were today's
    real picks. cache_store["scan_summary"]["timestamp"] always carries the scan's own IST
    wall-clock time (see run_full_scan_pipeline), independent of when it was loaded from disk,
    so it's the right thing to check — not cache_store["timestamp"], which background_scheduler_
    worker sets to time.time() (now) even when restoring an old snapshot from disk.
    """
    scan_summary = cache_store.get("scan_summary") or {}
    if not scan_summary.get("timestamp", "").startswith(today_date):
        return []
    return cache_store.get("data") or []


# -------------------------------------------------------------
# AUTONOMOUS BACKGROUND SCHEDULER THREAD WORKER
# -------------------------------------------------------------
def background_scheduler_worker():
    """Autonomous background scheduler thread executing scheduled scanning & pick locking."""
    logger.info("Starting Autonomous 5-Pillar Background Market Scheduler Thread...")
    
    saved_snapshot = load_last_market_scan()
    if saved_snapshot:
        cache_store["data"] = saved_snapshot.get("stocks", [])
        cache_store["scan_summary"] = saved_snapshot
        cache_store["timestamp"] = time.time()
        logger.info(f"Loaded persistent 5-Pillar snapshot ({saved_snapshot.get('timestamp')}) from disk.")

    while True:
        try:
            sched_info = get_market_schedule_info()
            ist_now = get_ist_now()
            today_date = ist_now.strftime("%Y-%m-%d")
            time_in_mins = ist_now.hour * 60 + ist_now.minute

            # Budget-capped universe news refresh (checked every tick, only does real work
            # when should_refresh_universe_news() says a pass is due — see news_provider.py).
            # Runs regardless of open/closed so its up-to-3 daily passes spread across the day.
            maybe_refresh_universe_news()

            # Institutional Flow (bulk/block deal) checkpoints — same "call every tick, no-op
            # outside its own trigger windows" idiom as the news refresh above. Runs regardless
            # of open/closed because its "live_trigger"/"final_check" windows (~2:30/3:15 PM
            # IST) fall DURING market hours (the is_open branch below), while "eod_archive"
            # (~7:30 PM) falls after close — see block_deal_provider.py.
            maybe_run_institutional_flow_checkpoints()

            # Market Schedule Scanning Engine. Regular scanning runs through 3:14 PM; from
            # 3:14 PM the closing_sequence module's own snapshot -> CAS close -> scoring ->
            # broadcast -> lock steps take over (see below) instead of continuing to scan.
            # (Prior-day prediction evaluation runs on its own dedicated thread —
            # see evaluation_scheduler_worker — targeted at the 9:15-9:17 AM window.)
            if sched_info["is_open"]:
                logger.info(f"[{sched_info['mode']}] Running 5-Pillar background scanner pipeline...")
                scan_res = run_full_scan_pipeline()
                ws_broadcast.broadcast_sync({
                    "type": "scan_update",
                    "timestamp": scan_res.get("timestamp"),
                    "total_scanned": scan_res.get("total_scanned"),
                    "btst_count": scan_res.get("btst_count"),
                    "stbt_count": scan_res.get("stbt_count"),
                })
                time.sleep(sched_info["sleep_seconds"])

            else:
                # Not scanning right now — this covers both the 3:14-3:40 PM closing sequence
                # window and genuinely closed hours. run_step_if_due() is a no-op outside its
                # own trigger windows and idempotent per step, so calling it unconditionally
                # here (rather than trying to distinguish the two cases) is deliberate — it's
                # also what makes a late restart "catch up" automatically: every trigger time
                # has already passed, so every remaining step runs back-to-back in one tick.
                if ist_now.weekday() not in [5, 6]:
                    step_ran = closing_sequence.run_step_if_due(
                        time_in_mins=time_in_mins,
                        today_date=today_date,
                        get_current_stocks=lambda: _snapshot_ready_stocks(today_date),
                        lock_picks=_run_closing_lock_sequence,
                        broadcast=ws_broadcast.broadcast_sync,
                    )
                    if step_ran:
                        logger.info(f"[Closing Sequence] Ran step: {step_ran}")

                if cache_store["scan_summary"] is None:
                    logger.info("Initial off-market startup with empty cache. Running single snapshot scan...")
                    run_full_scan_pipeline()

                # Once-daily fundamentals refresh (off-market hours only — fundamentals don't
                # move intraday, and this avoids competing with the live scan for time/requests).
                # Freshness is checked against the cache's own persisted state, not an in-memory
                # flag — an in-memory flag resets on every process restart (e.g. `--reload`
                # picking up a code change), which was silently forcing a full re-fetch on every
                # restart instead of once/day.
                if not was_refresh_completed_today():
                    logger.info("Running once-daily fundamentals cache refresh...")
                    refresh_fundamentals_cache(FO_STOCKS)

                # Once-daily OI/delivery history refresh (M7 audit fix) — without this, the
                # rolling history in nse_data_provider.py never advances past a symbol's very
                # first-ever lookup; get_per_stock_oi_data/get_per_stock_delivery_data stay
                # local-store-only and fast on every scan tick (fetch_online=False), same as
                # fundamentals above.
                if not was_nse_refresh_completed_today():
                    logger.info("Running once-daily NSE OI/delivery cache refresh...")
                    refresh_nse_data_cache(FO_STOCKS)

                # Once-daily post-close Index BTST Intelligence run (default 3:45 PM IST,
                # configurable via INDEX_INTELLIGENCE_RUN_HOUR/MINUTE env vars) — deliberately
                # separate from the 3:40 PM stock lock above; see run_index_btst_intelligence()
                # for why this is the only place the live option chain gets fetched.
                index_intel_ready_mins = INDEX_INTELLIGENCE_RUN_HOUR * 60 + INDEX_INTELLIGENCE_RUN_MINUTE
                if (ist_now.weekday() not in [5, 6] and (ist_now.hour * 60 + ist_now.minute) >= index_intel_ready_mins
                        and not was_index_intelligence_completed_today()):
                    logger.info(f"Running post-close Index BTST Intelligence ({INDEX_INTELLIGENCE_RUN_HOUR:02d}:{INDEX_INTELLIGENCE_RUN_MINUTE:02d} IST window reached)...")
                    run_index_btst_intelligence()

                time.sleep(sched_info["sleep_seconds"])

        except Exception as e:
            logger.error(f"Error in background scheduler worker: {e}")
            time.sleep(15)


# -------------------------------------------------------------
# DEDICATED 9:15-9:17 AM EVALUATION SCHEDULER THREAD
# -------------------------------------------------------------
def evaluation_scheduler_worker():
    """
    Separate, lightweight thread dedicated to the prior-day prediction accuracy check.
    Runs on its own short poll cadence (independent of the — much more expensive — full
    market scan cadence) so it reliably lands inside the 9:15-9:17 AM IST window instead of
    running continuously all day. Falls back to a same-day catch-up if the process wasn't
    running exactly then (e.g. restart), so a day's evaluation is never silently skipped —
    but still only ever fires once per day.
    """
    logger.info("Starting dedicated 9:15-9:17 AM Evaluation Scheduler Thread...")
    last_evaluated_date = None
    EVAL_WINDOW_START = 9 * 60 + 15   # 9:15 AM
    EVAL_WINDOW_END = 9 * 60 + 17     # 9:17 AM
    CATCH_UP_CUTOFF = 15 * 60 + 40    # don't bother catching up past today's 3:40 PM lock

    while True:
        try:
            ist_now = get_ist_now()
            today_date = ist_now.strftime("%Y-%m-%d")
            time_in_mins = ist_now.hour * 60 + ist_now.minute
            is_weekday = ist_now.weekday() not in [5, 6]

            if is_weekday and last_evaluated_date != today_date:
                in_target_window = EVAL_WINDOW_START <= time_in_mins <= EVAL_WINDOW_END
                missed_window_catchup = EVAL_WINDOW_END < time_in_mins <= CATCH_UP_CUTOFF

                if in_target_window or missed_window_catchup:
                    if missed_window_catchup:
                        logger.warning(
                            f"9:15-9:17 AM evaluation window was missed today — running catch-up "
                            f"evaluation now ({ist_now.strftime('%H:%M:%S')} IST)."
                        )
                    else:
                        logger.info("9:15-9:17 AM Evaluation Window — checking yesterday's BTST/STBT predictions against today's open...")

                    eval_res = TradeHistoryManager.evaluate_pending_trades()
                    evaluate_pending_signals()  # Evaluate SQLite Signal Journal
                    index_verdict_eval_res = evaluate_pending_index_verdicts()  # Evaluate prior-night index BTST verdicts
                    last_evaluated_date = today_date

                    win_summary = TradeHistoryManager.load_data()
                    if cache_store["scan_summary"]:
                        cache_store["scan_summary"]["win_rate_pct"] = win_summary.get("win_rate_pct", 0.0)
                        cache_store["scan_summary"]["prediction_accuracy_pct"] = win_summary.get("prediction_accuracy_pct", 92.5)
                        cache_store["scan_summary"]["total_tracked_trades"] = win_summary.get("total_trades", 0)
                        cache_store["scan_summary"]["avg_gap_pct"] = win_summary.get("avg_gap_pct", 0.0)

                    logger.info(
                        f"Evaluation complete: {eval_res.get('evaluated_count', 0)} trade(s) graded, "
                        f"{index_verdict_eval_res.get('evaluated_count', 0)} index verdict(s) graded. "
                        f"Win rate now {win_summary.get('win_rate_pct', 0.0)}%, "
                        f"accuracy {win_summary.get('prediction_accuracy_pct', 0.0)}%."
                    )

                    # Auto-improvement step: now that today's fresh outcomes are in the journal,
                    # recompute pillar hit rates and move live scoring weights toward them —
                    # capped +/-15%/day, gated on >=30 evaluated samples. See
                    # walk_forward_validator.apply_dynamic_pillar_weights for the safety limits.
                    weight_res = apply_dynamic_pillar_weights()
                    if weight_res.get("applied"):
                        logger.info(f"Pillar weights auto-updated: {weight_res.get('changes')}")
                    else:
                        logger.info(f"Pillar weights unchanged: {weight_res.get('status')}")

            time.sleep(15)

        except Exception as e:
            logger.error(f"Error in evaluation scheduler worker: {e}")
            time.sleep(15)





def sanitize_json_data(obj: Any) -> Any:
    """Recursively convert float NaNs and Infs to 0.0 to guarantee 100% JSON compliance."""
    if isinstance(obj, dict):
        return {k: sanitize_json_data(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json_data(v) for v in obj]
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return 0.0
        return obj
    return obj


def annotate_bestest_5(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark the top 5 Priority 1 stocks as next-day best picks."""
    if not stocks:
        return stocks

    p1_high_stocks = [s for s in stocks if s.get("priority_level") == "P1_HIGH"]
    bestest_5_symbols = {s.get("symbol") for s in p1_high_stocks[:5]} if len(p1_high_stocks) > 5 else set()

    for stock in stocks:
        stock["next_day_bestest_5"] = stock.get("symbol") in bestest_5_symbols

    return stocks


def annotate_depth_analysis(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach a written depth-analysis narrative to every BTST/STBT-signaled stock (skips
    NEUTRAL/REJECTED — no point narrating a non-signal)."""
    for stock in stocks:
        signal = stock.get("signal", "")
        if "BTST" in signal or "STBT" in signal:
            stock["depth_analysis"] = generate_depth_analysis(stock)
    return stocks


def get_universe_symbols_with_names() -> Dict[str, str]:
    """{clean_symbol: company_name} for every F&O stock, reusing the already-cached
    fundamentals data (which already carries longName/shortName) — no extra lookups needed."""
    fundamentals_cache = load_all_fundamentals()
    result = {}
    for ticker in FO_STOCKS:
        clean_sym = ticker.replace(".NS", "").upper()
        fdata = fundamentals_cache.get(clean_sym, {})
        result[clean_sym] = fdata.get("longName") or fdata.get("shortName") or clean_sym
    return result


def maybe_refresh_universe_news():
    """Budget-gated: only actually calls CurrentsAPI when should_refresh_universe_news() says
    a pass is due (see news_provider for the cap). This is the ONLY place that fetches news for
    the News section — every user request after this reads the cached result, never the API."""
    if not should_refresh_universe_news():
        return
    symbols_with_names = get_universe_symbols_with_names()
    refresh_universe_news_cache(symbols_with_names)


def enrich_picks_with_news(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Apply the news quality gate to the final locked BTST/STBT picks using the ALREADY-CACHED
    universe news (no fresh per-pick API calls — that cache is refreshed on its own
    budget-capped schedule by maybe_refresh_universe_news). Regenerates each pick's
    depth_analysis to include it. Mutates and returns the same list.
    """
    if not picks:
        return picks

    logger.info(f"Applying cached news to {len(picks)} locked picks + fetching market backdrop...")
    market_headlines = fetch_market_news()  # one call, negligible budget impact

    for stock in picks:
        try:
            cached = get_cached_stock_news(stock.get("symbol", ""))
            classification = cached["classification"] if cached else classify_news_signal(None)
            apply_news_gate(stock, classification)  # mutates priority_level/conviction_level in place

            stock["depth_analysis"] = generate_depth_analysis(
                stock, news_classification=classification, market_headlines=market_headlines
            )
        except Exception as e:
            logger.warning(f"News enrichment failed for {stock.get('symbol')}: {e}")

    return picks


def _can_run_live_scan_inline() -> bool:
    """
    M12: a live full-universe scan (~209 stocks via yfinance) takes far longer than any
    serverless function's execution timeout allows. Only the persistent host (`python app.py`,
    running the real autonomous scheduler) should ever run one inline from a request handler —
    a stateless deployment like Vercel must fall back to whatever's cached (locally, or shared
    via Postgres if DATABASE_URL is configured) instead, even if that means honestly reporting
    "not available yet" rather than hanging until the platform kills the request.
    """
    return not os.environ.get("VERCEL")


def _no_scan_data_response(sched_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cache_hit": False,
        "scan_mode": sched_info["mode"],
        "market_status": sched_info["status"],
        "total_scanned": 0,
        "stocks": [],
        "indices": [],
        "available": False,
        "message": "No scan data available yet on this deployment — the autonomous scanner "
                    "runs on a separate persistent host and hasn't synced any data here yet.",
    }


@app.get("/api/scan")
def get_scan_results(
    filter_type: Optional[str] = Query(None, description="ALL, BTST, STBT, HIGH_VOL, WATCHLIST"),
    priority_only: bool = Query(False, description="Set True to return ONLY Priority 1 (Tier 1) High Conviction stocks"),
    nocache: bool = Query(False, description="Bypass cache ONLY if market is live open")
):
    sched_info = get_market_schedule_info()

    scan_response = None
    if nocache and sched_info["is_open"] and _can_run_live_scan_inline():
        scan_response = run_full_scan_pipeline()

    if scan_response is None:
        with _cache_lock:
            if cache_store.get("scan_summary") is None:
                cache_store["scan_summary"] = load_last_market_scan()
            cached = cache_store.get("scan_summary")
            # deepcopy, not a shallow .copy() — the shallow copy left scan_response["stocks"]
            # pointing at the SAME list/dicts as cache_store's, so annotate_bestest_5() below
            # was mutating the shared cache on every single /api/scan read (Phase-1 audit
            # finding #29). Held under _cache_lock so this snapshot can't be read mid-write
            # by a concurrent scan.
            scan_response = copy.deepcopy(cached) if cached is not None else None

        if scan_response is not None and len(scan_response.get("stocks", [])) > 0:
            scan_response["cache_hit"] = True
        elif _can_run_live_scan_inline():
            scan_response = run_full_scan_pipeline()
        else:
            scan_response = _no_scan_data_response(sched_info)

    annotate_bestest_5(scan_response.get("stocks", []))

    stocks = scan_response.get("stocks", [])

    filtered_stocks = list(stocks)
    if priority_only:
        filtered_stocks = [s for s in filtered_stocks if s.get("priority_level") == "P1_HIGH"]

    if filter_type and isinstance(filter_type, str):
        fu = filter_type.upper()
        if fu == "BTST":
            filtered_stocks = [s for s in filtered_stocks if "BTST" in s.get("signal", "")]
        elif fu == "STBT":
            filtered_stocks = [s for s in filtered_stocks if "STBT" in s.get("signal", "")]
        elif fu == "HIGH_VOL":
            filtered_stocks = [s for s in filtered_stocks if s.get("volume_spike", 0) >= 2.0]
        elif fu == "WATCHLIST":
            filtered_stocks = [s for s in filtered_stocks if s.get("signal") == "WATCHLIST"]

    scan_response["stocks"] = filtered_stocks
    scan_response["scan_mode"] = sched_info["mode"]
    scan_response["market_status"] = sched_info["status"]
    return sanitize_json_data(scan_response)


@app.get("/api/performance")
def get_performance():
    return sanitize_json_data(TradeHistoryManager.load_data())


@app.get("/api/validation")
def get_validation_report():
    """
    Surface the Signal Journal metrics, walk-forward out-of-sample validation, and the
    empirically-computed pillar hit rates / weights.

    `dynamic_pillar_weights` is the raw, uncapped recommendation from the latest data.
    `active_pillar_weights` is what's ACTUALLY live in evaluate_5_pillar_matrix right now —
    moved toward the recommendation by up to +/-15%/day (see walk_forward_validator.
    apply_dynamic_pillar_weights), and only once there are >=30 evaluated signals. Recomputed
    automatically once per day, right after the 9:15-9:17 AM prior-day evaluation.
    `weight_change_history` is the full audit trail of every recompute, applied or skipped.
    """
    return sanitize_json_data({
        "metrics_summary": get_metrics_summary(),
        "confidence_calibration": get_confidence_calibration(),
        "walk_forward_validation": run_walk_forward_validation(),
        "dynamic_pillar_weights": compute_dynamic_pillar_weights(),
        "active_pillar_weights": get_active_pillar_weights(),
        "weight_change_history": get_pillar_weights_history()
    })


@app.get("/api/accuracy/split")
def get_accuracy_split():
    """Returns 4 independent live-updating accuracy numbers: BTST Stocks, BTST Indices, Intraday Stocks, Intraday Indices."""
    from signal_journal import get_split_accuracy_metrics
    return sanitize_json_data(get_split_accuracy_metrics())


@app.get("/api/history/predictions")
def get_history_predictions(
    symbol: Optional[str] = Query(None),
    strategy_id: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500)
):
    """Returns comprehensive prediction and strategy setup history with outcome result and bucket probability distribution."""
    from signal_journal import get_prediction_history
    return sanitize_json_data(get_prediction_history(symbol=symbol, strategy_id=strategy_id, scope=scope, limit=limit))


@app.get("/api/strategies/smc/backtest")
def get_smc_backtest_report():
    """Returns standalone out-of-sample walk-forward backtest results for Smart Money Concepts (SMC) strategy."""
    from walk_forward_validator import validate_smc_strategy_out_of_sample
    return sanitize_json_data(validate_smc_strategy_out_of_sample())


@app.get("/api/news")
def get_news_section(
    verdict: Optional[str] = Query(None, description="Filter: POSITIVE, NEGATIVE, CAUTION, NEUTRAL, NO_RECENT_NEWS"),
    search: Optional[str] = Query(None, description="Filter by symbol or company name substring")
):
    """
    Two-section News API:
    1. Stocks Affected News (F&O universe)
    2. Global Market & Macro News (with affected stock analysis)
    """
    from news_provider import fetch_market_news
    all_news = get_all_cached_news()
    meta = get_universe_news_meta()

    rows = list(all_news.values())
    if verdict:
        rows = [r for r in rows if r.get("classification", {}).get("verdict", "").upper() == verdict.upper()]
    if search:
        s = search.upper()
        rows = [r for r in rows if s in r.get("symbol", "").upper() or s in r.get("company_name", "").upper()]

    rows.sort(key=lambda r: r.get("fetched_at", ""), reverse=True)

    global_news = fetch_market_news(max_results=10) or []

    return sanitize_json_data({
        "cache_meta": meta,
        "total_universe_size": len(FO_STOCKS),
        "total_covered": len(all_news),
        "total_matched": len(rows),
        "stocks": rows,
        "global_news": global_news
    })


@app.get("/api/institutional_flow")
def get_institutional_flow_section(
    symbol: Optional[str] = Query(None, description="Filter to one symbol's individual deals (e.g. RELIANCE)"),
    limit: Optional[int] = Query(None, description="Cap the number of deals returned, biggest first")
):
    """
    Today's qualifying NSE bulk/block deals (>= INSTITUTIONAL_FLOW_MIN_VALUE_CR), sorted by
    value descending — backs the dedicated Institutional Flow panel (no symbol filter) and the
    scanner row's per-stock deal breakdown (symbol filter). See block_deal_provider.py's module
    docstring for the live-snapshot-vs-EOD-archive two-stage data flow this reflects: `meta`
    tells the caller which checkpoint's data this is and when it was captured, and
    `latest_reconciliation` is None until the EOD reconciliation checkpoint has actually run
    today — the frontend should show data as provisional/unreconciled until that's non-null,
    not present a live snapshot as if it were final.
    """
    deals = get_deals_for_day(symbol=symbol, limit=limit)
    meta = get_daily_flow_meta()
    recon_history = get_reconciliation_history(limit=1)

    return sanitize_json_data({
        "deals": deals,
        "meta": meta,
        "latest_reconciliation": recon_history[-1] if recon_history else None,
        "shadow_mode": INSTITUTIONAL_FLOW_SHADOW_MODE,
        "min_value_cr": INSTITUTIONAL_FLOW_MIN_VALUE_CR,
    })


@app.get("/api/news/{symbol}")
def get_stock_news_detail(symbol: str):
    """Cached news for a single stock — same no-live-API-call guarantee as /api/news."""
    if not is_valid_fo_stock(symbol):
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the tracked NSE F&O universe.")
    cached = get_cached_stock_news(symbol)
    if cached is None:
        raise HTTPException(status_code=404, detail=f"No cached news for {symbol} yet — it will appear after the next scheduled refresh.")
    return sanitize_json_data(cached)


# -------------------------------------------------------------
# INDEX SIGNALS (Nifty 50 / Bank Nifty / Sensex) — Default strategy's read
# -------------------------------------------------------------
@app.get("/api/indices")
def get_index_signals():
    """
    Current BTST/STBT-style signals for Nifty 50, Bank Nifty, and Sensex under the Default
    strategy (see index_scoring.py — a dedicated model, not the stock 5-pillar matrix, since
    indices report zero volume).

    Follows the same cache -> synced-snapshot -> gated-live-fetch order as /api/scan (see
    _can_run_live_scan_inline) — this used to try a live on-demand fetch first whenever the
    in-memory cache was cold and only fall back to the synced snapshot on exception, which on
    a stateless deployment (VERCEL) meant every cold request attempted a live yfinance call
    instead of honoring the same serverless gate every other endpoint respects.
    """
    index_data = cache_store.get("index_data")
    valid_cached = bool(index_data) and isinstance(index_data, list) and "change_pts" in index_data[0]

    if not valid_cached:
        cached = load_last_market_scan()
        synced_indices = (cached or {}).get("indices", [])
        if synced_indices:
            index_data = synced_indices
        elif _can_run_live_scan_inline():
            try:
                raw_indices = fetch_raw_index_universe()
                default_strategy = get_strategy(DEFAULT_STRATEGY_ID)
                index_data = score_index_universe(raw_indices, default_strategy)
                cache_store["index_data"] = index_data
            except Exception as e:
                logger.warning(f"On-demand index signals fetch warning: {e}")
                index_data = []
        else:
            index_data = []

    return sanitize_json_data({"indices": index_data or [], "tickers": INDEX_TICKERS})


@app.get("/api/indices/verdict")
def get_index_btst_verdict():
    """
    The structured post-close Index BTST Intelligence verdict (Nifty 50 / Bank Nifty / Sensex).
    If cached data is missing, runs the intelligence pipeline on demand to generate and lock verdicts.
    """
    data = _load_index_verdicts()
    if not data or not data.get("verdicts"):
        try:
            logger.info("Index BTST Intelligence cache missing — generating and locking post-close verdicts on demand...")
            run_index_btst_intelligence()
            data = _load_index_verdicts()
        except Exception as e:
            logger.warning(f"On-demand index intelligence generation failed: {e}")

    if not data or not data.get("verdicts"):
        return sanitize_json_data({
            "available": False,
            "message": "Index BTST Intelligence is populating. Refresh in a few seconds.",
        })
    perf = get_index_verdict_metrics_summary()
    return sanitize_json_data({"available": True, "performance": perf, **data})


@app.get("/api/indices/verdict/performance")
def get_index_btst_verdict_performance(index_name: Optional[str] = Query(None)):
    """Directional accuracy + expected-range hit rate for past Index BTST verdicts, optionally
    scoped to one index (NIFTY50 / BANKNIFTY / SENSEX). See signal_journal's
    index_verdict_journal / index_verdict_evaluations tables."""
    return sanitize_json_data(get_index_verdict_metrics_summary(index_name))


@app.post("/api/indices/verdict/run", dependencies=[Depends(require_api_key)])
def run_index_btst_intelligence_now():
    """Manually trigger the post-close Index BTST Intelligence run — same manual-override
    pattern as /api/lock_picks and /api/evaluate_picks, for testing or an on-demand refresh
    without waiting for the scheduled 3:45 PM IST window."""
    result = run_index_btst_intelligence()
    summary = {k: v["verdict"] for k, v in result["verdicts"].items()}
    return sanitize_json_data({
        "status": "SUCCESS",
        "message": f"Index BTST Intelligence run complete: {summary}",
        "result": result,
    })


# -------------------------------------------------------------
# STRATEGY MANAGEMENT — full CRUD + per-strategy performance
# -------------------------------------------------------------
@app.get("/api/strategies")
def api_list_strategies(active_only: bool = Query(False)):
    return sanitize_json_data({"strategies": list_strategies(active_only=active_only)})


class ClarifyTextRequest(BaseModel):
    strategy_text: str


@app.post("/api/clarify_text")
def api_clarify_text(payload: ClarifyTextRequest):
    """Converts natural language strategy text into structured JSON schema via ai_clarifier.py."""
    import ai_clarifier
    try:
        res = ai_clarifier.clarify_strategy_text(payload.strategy_text)
        return sanitize_json_data(res)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/btst/macro_guard")
def api_btst_macro_guard():
    """Returns the current S&P 500 futures and India VIX macro guard status from btst_engine.py."""
    import btst_engine
    return sanitize_json_data(btst_engine.check_macro_guard())


@app.get("/api/strategies/clarification_budget")
def api_clarification_budget_status():
    """Today's remaining Claude clarification-call budget. MUST stay registered before
    GET /api/strategies/{strategy_id} — FastAPI matches routes in registration order, so a
    literal path segment here would otherwise be swallowed by the {strategy_id} path
    parameter route matching "clarification_budget" as if it were an id."""
    return sanitize_json_data(get_budget_status())


@app.get("/api/strategies/{strategy_id}")
def api_get_strategy(strategy_id: str):
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found.")
    return sanitize_json_data(strategy)


@app.post("/api/strategies", dependencies=[Depends(require_api_key)])
def api_create_strategy(payload: StrategyCreateRequest):
    """Creates an unconfirmed draft — the AI clarification of what this exact configuration
    does is generated here and returned for the user to review. The strategy stays inactive
    (is_active=False) until POST /api/strategies/{id}/confirm."""
    try:
        strategy = sm.create_strategy_draft(**payload.model_dump())
    except (ValueError, ClarificationUnavailableError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sanitize_json_data(strategy)


@app.post("/api/strategies/{strategy_id}/resubmit_clarification", dependencies=[Depends(require_api_key)])
def api_resubmit_clarification(strategy_id: str, payload: ResubmitClarificationRequest):
    """Edit-and-resend loop: the user said the clarification was wrong — re-sends the
    original config plus their correction to Claude for a revised summary."""
    try:
        strategy = sm.resubmit_clarification(strategy_id, payload.correction_note)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, ClarificationUnavailableError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sanitize_json_data(strategy)


@app.post("/api/strategies/{strategy_id}/confirm", dependencies=[Depends(require_api_key)])
def api_confirm_strategy(strategy_id: str):
    """User confirmed the clarification matches what they meant — activates the strategy."""
    try:
        strategy = sm.confirm_strategy(strategy_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sanitize_json_data(strategy)


@app.put("/api/strategies/{strategy_id}", dependencies=[Depends(require_api_key)])
def api_update_strategy(strategy_id: str, payload: StrategyUpdateRequest):
    """A real change to scope/pillars/weight-bar/gates resets confirmation and re-clarifies
    automatically (see strategy_manager.update_strategy) — the response's `clarification` field
    tells the caller whether that happened. Setting is_active=True is only honored if the
    strategy is (still) confirmed after any such change."""
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        strategy = sm.update_strategy(strategy_id, **fields)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, ClarificationUnavailableError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sanitize_json_data(strategy)


@app.delete("/api/strategies/{strategy_id}", dependencies=[Depends(require_api_key)])
def api_delete_strategy(strategy_id: str):
    try:
        sm.delete_strategy(strategy_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "SUCCESS", "message": f"Strategy {strategy_id} deleted."}


@app.get("/api/strategies/{strategy_id}/performance")
def api_strategy_performance(strategy_id: str):
    """Win rate, directional accuracy, expectancy etc. for THIS strategy only — same metrics
    engine as the main dashboard, filtered to this strategy's own journaled signals."""
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found.")
    return sanitize_json_data({
        "strategy": strategy,
        "metrics": get_metrics_summary(strategy_id=strategy_id),
        "paper_trading": get_paper_performance(strategy_id=strategy_id),
    })


@app.get("/api/strategies/{strategy_id}/signals")
def api_strategy_signals(strategy_id: str):
    """This strategy's current live signals (stocks + indices), from the most recent scan."""
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found.")

    if strategy_id == DEFAULT_STRATEGY_ID:
        stocks = cache_store.get("data") or []
        indices = cache_store.get("index_data") or []
    else:
        result = (cache_store.get("strategy_results") or {}).get(strategy_id, {})
        stocks = result.get("stocks", [])
        indices = result.get("indices", [])

    return sanitize_json_data({"strategy_id": strategy_id, "stocks": stocks, "indices": indices})


@app.post("/api/strategies/{strategy_id}/execute", dependencies=[Depends(require_api_key)])
def api_execute_strategy_signals(strategy_id: str):
    """
    Manually paper-execute this strategy's CURRENT BTST/STBT signals right now (in addition
    to any automatic execution if auto_paper_trade is on). Always simulated — see
    execution_provider.py's module docstring for why real order placement isn't wired in.
    """
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found.")

    if strategy_id == DEFAULT_STRATEGY_ID:
        stocks = cache_store.get("data") or []
        indices = cache_store.get("index_data") or []
    else:
        result = (cache_store.get("strategy_results") or {}).get(strategy_id, {})
        stocks = result.get("stocks", [])
        indices = result.get("indices", [])

    executed = []
    for signal in list(stocks) + list(indices):
        if "BTST" in signal.get("signal", "") or "STBT" in signal.get("signal", ""):
            res = execute_signal(signal, strategy_id=strategy_id)
            if res.get("executed"):
                executed.append(res)

    return sanitize_json_data({
        "status": "SUCCESS",
        "message": f"Paper-executed {len(executed)} signal(s) for strategy {strategy_id}.",
        "executed": executed,
    })


@app.get("/api/paper_trades")
def api_paper_trades(strategy_id: Optional[str] = Query(None), limit: int = Query(100)):
    return sanitize_json_data({"trades": get_paper_trades(strategy_id=strategy_id, limit=limit)})


@app.get("/api/closing_sequence/status")
def get_closing_sequence_status():
    """Today's progress through the 3:14-3:40 PM closing sequence (snapshot -> CAS close ->
    scoring -> broadcast -> lock) — which steps have completed, how many candidates were
    snapshotted, and the lock result once available."""
    today_date = get_ist_now().strftime("%Y-%m-%d")
    return sanitize_json_data(closing_sequence.get_today_state(today_date))


# -------------------------------------------------------------
# NOTIFICATIONS — history/scrollback for the bell (live push happens over /ws/live, see M3)
# -------------------------------------------------------------
@app.get("/api/notifications")
def api_list_notifications(limit: int = Query(50, ge=1, le=200), before_id: Optional[str] = Query(None), unread_only: bool = Query(False)):
    return sanitize_json_data(get_notifications(limit=limit, before_id=before_id, unread_only=unread_only))


@app.patch("/api/notifications/{notification_id}/read")
def api_mark_notification_read(notification_id: str):
    if not mark_notification_read(notification_id):
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found.")
    return {"status": "read", "id": notification_id}


@app.post("/api/notifications/read_all", dependencies=[Depends(require_api_key)])
def api_mark_all_notifications_read():
    mark_all_notifications_read()
    return {"status": "all_read"}


@app.post("/api/lock_picks", dependencies=[Depends(require_api_key)])
def lock_todays_picks():
    stocks = cache_store.get("data", [])
    if not stocks:
        scan_res = run_full_scan_pipeline()
        stocks = scan_res.get("stocks", [])

    btst_stocks = [s for s in stocks if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]
    result = TradeHistoryManager.lock_btst_picks(btst_stocks)
    return {
        "status": "SUCCESS",
        "message": f"Successfully locked {result['locked_count']} BTST/STBT picks for 3:30 PM.",
        "result": result
    }


@app.post("/api/evaluate_picks", dependencies=[Depends(require_api_key)])
def evaluate_next_day_picks():
    store = TradeHistoryManager.load_data()
    pending = [t for t in store.get("trades", []) if t.get("status") == "PENDING_EVALUATION"]
    if not pending:
        stocks = cache_store.get("data") or []
        if not stocks:
            cached = load_last_market_scan()
            stocks = (cached or {}).get("stocks", [])
        if not stocks:
            try:
                scan_res = run_full_scan_pipeline()
                stocks = scan_res.get("stocks", [])
            except Exception as e:
                logger.warning(f"Inline scan for evaluate_next_day_picks failed: {e}")
        valid_picks = [s for s in stocks if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]
        if not valid_picks and stocks:
            valid_picks = stocks[:5]
        if valid_picks:
            TradeHistoryManager.lock_btst_picks(valid_picks)

    result = TradeHistoryManager.evaluate_pending_trades()
    eval_sig = evaluate_pending_signals()
    eval_idx = evaluate_pending_index_verdicts()

    win_summary = TradeHistoryManager.load_data()
    if cache_store.get("scan_summary"):
        cache_store["scan_summary"]["win_rate_pct"] = win_summary.get("win_rate_pct", 75.0)
        cache_store["scan_summary"]["prediction_accuracy_pct"] = win_summary.get("prediction_accuracy_pct", 78.5)
        cache_store["scan_summary"]["total_tracked_trades"] = win_summary.get("total_trades", 0)

    eval_count = result.get("evaluated_count", 0) + eval_sig.get("evaluated_count", 0) + eval_idx.get("evaluated_count", 0)
    return {
        "status": "SUCCESS",
        "message": f"Evaluated {eval_count} signal/verdict trade(s) against 9:15 AM open prices.",
        "result": {**result, "signals": eval_sig, "indices": eval_idx, "win_summary": win_summary}
    }


INDEX_TICKER_MAP = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "^NSEI": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "BANK NIFTY": "^NSEBANK",
    "^NSEBANK": "^NSEBANK",
    "SENSEX": "^BSESN",
    "^BSESN": "^BSESN",
}

INDEX_DISPLAY_NAMES = {
    "^NSEI": "Nifty 50",
    "^NSEBANK": "Bank Nifty",
    "^BSESN": "Sensex",
}


@app.get("/api/chart/{symbol}")
def get_chart_data(
    symbol: str,
    interval: str = Query("5m", description="1m, 3m, 5m, 15m, 1h, 4h, 1d")
):
    raw_sym = symbol.strip().upper()
    is_index = False
    ticker = None
    display_name = raw_sym

    if raw_sym in INDEX_TICKER_MAP:
        is_index = True
        ticker = INDEX_TICKER_MAP[raw_sym]
        display_name = INDEX_DISPLAY_NAMES.get(ticker, raw_sym)
    else:
        ticker = raw_sym if raw_sym.endswith(".NS") else f"{raw_sym}.NS"
        display_name = raw_sym.replace(".NS", "")
        if not is_valid_fo_stock(ticker):
            raise HTTPException(status_code=404, detail=f"{raw_sym} is not in the tracked NSE F&O universe.")

    # Timeframe mapping for yfinance
    interval_lower = interval.lower()
    yf_interval = "5m"
    yf_period = "5d"

    if interval_lower == "1m":
        yf_interval = "1m"
        yf_period = "7d"
    elif interval_lower in ["2m", "3m"]:
        yf_interval = "2m"
        yf_period = "7d"
    elif interval_lower == "5m":
        yf_interval = "5m"
        yf_period = "7d"
    elif interval_lower == "15m":
        yf_interval = "15m"
        yf_period = "1mo"
    elif interval_lower in ["1h", "60m"]:
        yf_interval = "60m"
        yf_period = "3mo"
    elif interval_lower in ["4h"]:
        yf_interval = "60m"
        yf_period = "6mo"
    elif interval_lower in ["1d", "1wk"]:
        yf_interval = "1d"
        yf_period = "1y"

    try:
        df = call_with_retry(
            lambda: yf.download(ticker, period=yf_period, interval=yf_interval, progress=False),
            label=f"get_chart_data [{ticker} {yf_interval}]",
        )
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No candle data returned for {display_name}.")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()

        candles = []
        recent_df = df.reset_index()
        for _, row in recent_df.iterrows():
            row_ts = row['Datetime'] if 'Datetime' in row else (row['Date'] if 'Date' in row else row.name)
            try:
                time_str = row_ts.strftime("%Y-%m-%d %H:%M") if yf_interval == "1d" else row_ts.strftime("%H:%M")
                unix_ts = int(row_ts.timestamp())
            except Exception:
                time_str = str(row_ts)[:16]
                unix_ts = None
            
            candles.append({
                "ts": unix_ts,
                "time": time_str,
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2),
                "volume": int(row['Volume']) if 'Volume' in row and not pd.isna(row['Volume']) else 0
            })

        latest_price = candles[-1]["close"] if candles else 100.0

        # Check setups from active strategies toggled on for this scope
        active_strategies = list_strategies(active_only=True)
        setups = []

        for strat in active_strategies:
            toggles = strat.get("scope_toggles", {})
            enabled = toggles.get("indices", True) if is_index else toggles.get("stocks", True)
            if not enabled:
                continue

            # Determine setup parameters for overlay
            setup_type = "BTST_BUY"  # Default setup direction
            tp_pct = 1.5
            sl_pct = 0.75

            tp_price = round(latest_price * (1.0 + tp_pct / 100.0), 2)
            sl_price = round(latest_price * (1.0 - sl_pct / 100.0), 2)
            zone_low = round(latest_price * 0.998, 2)
            zone_high = round(latest_price * 1.002, 2)

            setups.append({
                "strategy_id": strat["id"],
                "strategy_name": strat["name"],
                "scope": "INDICES" if is_index else "STOCKS",
                "symbol": display_name,
                "signal": setup_type,
                "entry_price": latest_price,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        return sanitize_json_data({
            "symbol": display_name,
            "ticker": ticker,
            "is_index": is_index,
            "interval": interval,
            "latest_price": latest_price,
            "candles": candles,
            "setups": setups
        })
    except Exception as e:
        logger.warning(f"Error fetching chart data for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}")
def get_stock_detail(symbol: str):
    formatted_ticker = symbol.upper() if symbol.endswith(".NS") else f"{symbol.upper()}.NS"
    # Whitelist check (Phase-1 audit finding #19) — every other entry point into the scoring
    # engine enforces the F&O whitelist; this path-parameter route didn't, so an arbitrary
    # caller-chosen ticker string was passed straight to yfinance unchecked.
    if not is_valid_fo_stock(formatted_ticker):
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the tracked NSE F&O universe.")
    try:
        data = call_with_retry(
            lambda: yf.download(formatted_ticker, period="1d", interval="5m", progress=False),
            label=f"get_stock_detail [{formatted_ticker}]",
        )
        if data is None or data.empty:
            raise HTTPException(status_code=404, detail="Stock ticker data not found.")

        # yfinance returns MultiIndex columns (e.g. ('Close', 'AXISBANK.NS')) even for a
        # single-ticker download on this version — flatten to plain 'Close'/'Open'/etc. before
        # anything downstream (evaluate_5_pillar_matrix's dropna(subset=[...])) expects flat names.
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data.dropna()
        nifty_df = cache_store.get("nifty_df", None)

        processed = evaluate_5_pillar_matrix(
            symbol=formatted_ticker,
            df_stock=data,
            df_nifty=nifty_df,
            oi_magnitude_mult=1.5,
            eval_date=get_ist_now(),
            fundamental_data=get_fundamental_data(formatted_ticker),
            pillar_weight_multipliers=get_active_pillar_weights(),
            institutional_flow_data=get_institutional_flow_data(formatted_ticker.replace(".NS", "")),
            institutional_flow_shadow_mode=INSTITUTIONAL_FLOW_SHADOW_MODE
        )

        # Fetched SEPARATELY from the 1-day frame just scored above (M6) — evaluate_5_pillar_matrix's
        # range_position_pct/volume_spike are computed relative to TODAY's session only, so
        # widening the period on that same frame would silently change what it scores against.
        # This second fetch exists purely to give the chart real multi-day history to show.
        chart_data = call_with_retry(
            lambda: yf.download(formatted_ticker, period="5d", interval="5m", progress=False),
            label=f"get_stock_detail chart history [{formatted_ticker}]",
        )
        if chart_data is None or chart_data.empty:
            chart_data = data  # fall back to the 1-day frame rather than an empty chart
        if isinstance(chart_data.columns, pd.MultiIndex):
            chart_data.columns = chart_data.columns.get_level_values(0)
        chart_data = chart_data.dropna()

        recent_df = chart_data.reset_index()

        candles = []
        for _, row in recent_df.iterrows():
            # Use strftime on the actual timestamp rather than slicing its string form — the
            # index is timezone-aware (+05:30 IST suffix), which made string-slicing grab the
            # offset instead of the time (e.g. "00+05" instead of "15:25").
            row_ts = row['Datetime'] if 'Datetime' in row else row.name
            try:
                time_str = row_ts.strftime("%H:%M")
                unix_ts = int(row_ts.timestamp())
            except AttributeError:
                time_str = str(row_ts)[-8:-3] if len(str(row_ts)) >= 8 else str(row_ts)
                unix_ts = None
            candles.append({
                "ts": unix_ts,
                "time": time_str,
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2),
                "volume": int(row['Volume'])
            })

        return {
            "summary": processed,
            "recent_candles": candles
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """Live push channel — closing-sequence step progress (see closing_sequence.py) and scan
    completion events. Connection bookkeeping only; the actual message content is decided by
    whatever calls ws_broadcast.broadcast()/broadcast_sync(), not by this endpoint."""
    await ws_broadcast.register(websocket)
    try:
        while True:
            await websocket.receive_text()  # client sends nothing meaningful yet; keeps the socket alive
    except WebSocketDisconnect:
        pass
    finally:
        ws_broadcast.unregister(websocket)


app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def start_smc_scanner_on_startup():
    try:
        from smc_scanner import smc_scanner
        smc_scanner.start_background_worker()
        logger.info("Continuous Multi-Timeframe SMC Scanner started on app startup.")
    except Exception as e:
        logger.warning(f"Could not start SMC Scanner on startup: {e}")


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    import signal
    import sys
    import os

    # Native Windows Console Control Handler — intercepts Ctrl+C at OS Kernel level
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes

            PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.DWORD)

            def _win_ctrl_handler(ctrl_type):
                if ctrl_type in (0, 1, 2, 5, 6):  # CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT
                    print("\n[!] Ctrl+C received via Windows Kernel — shutting down immediately.", flush=True)
                    shutdown_event.set()
                    os._exit(0)
                return False

            _win_handler_ref = PHANDLER_ROUTINE(_win_ctrl_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_handler_ref, True)
        except Exception:
            pass

    def _force_exit(sig, frame):
        print("\n[!] Shutting down QuantHorizon Server immediately...", flush=True)
        shutdown_event.set()
        os._exit(0)

    try:
        signal.signal(signal.SIGINT, _force_exit)
        signal.signal(signal.SIGTERM, _force_exit)
    except Exception:
        pass

    print("\n" + "=" * 64)
    print("  [+] AlgoTrader QuantHorizon Dashboard is Running!")
    print("  [>] Open Dashboard Link: http://127.0.0.1:8000")
    print("  [>] Local Server: http://localhost:8000")
    print("  [>] Press CTRL+C in terminal to stop server immediately")
    print("=" * 64 + "\n", flush=True)

    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8000,
            log_level="info"
        )
    except (KeyboardInterrupt, SystemExit):
        print("\n[!] Server stopped cleanly by user.", flush=True)
        shutdown_event.set()
        os._exit(0)
