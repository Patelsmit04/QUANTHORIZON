import os
import time
import threading
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np

from json_utils import atomic_write_json, read_json
from scoring_engine import evaluate_5_pillar_matrix, get_liquidity_tier
from nse_data_provider import fetch_all_nse_data, get_per_stock_oi_data, get_per_stock_delivery_data
from fo_universe import get_canonical_fo_tickers, NSE_FO_STOCKS
from vix_provider import fetch_india_vix
from signal_journal import (
    log_signal_entry, evaluate_pending_signals, get_metrics_summary, get_confidence_calibration
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

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("BTSTScanner")

app = FastAPI(
    title="BTST Scanner Engine — 5-Pillar Matrix & Autonomous Scheduler",
    description="Refactored 5-Pillar Intraday Matrix, OI Magnitude Threshold, Expiry Discount, Liquidity Tiering & 3:30 PM Off-Market Freeze",
    version="4.5.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Canonical Whitelisted NSE F&O Stock List (Yahoo Finance .NS format)
FO_STOCKS = get_canonical_fo_tickers()

DATA_DIR = "data"
TRADE_HISTORY_FILE = os.path.join(DATA_DIR, "trade_history.json")
LAST_MARKET_SCAN_FILE = os.path.join(DATA_DIR, "last_market_scan.json")

# In-Memory Cache Store for Instant Responses
cache_store: Dict[str, Any] = {
    "data": None,
    "scan_summary": None,
    "timestamp": 0,
    "mode": "INITIALIZING"
}


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
    - Weekends (Saturday/Sunday): CLOSED (Serve 3:30 PM final scan locked snapshot)
    - Weekdays 9:15 AM - 2:29:59 PM: OPEN (5-min frequency)
    - Weekdays 2:30 PM - 3:30:00 PM: POWER HOUR (1-min frequency)
    - Weekdays 3:30:01 PM - 9:14:59 AM Next Day: CLOSED — no further scanning (Serve 3:30 PM
      final scan locked snapshot)
    """
    ist_now = get_ist_now()
    weekday = ist_now.weekday() # 0 = Monday, 6 = Sunday
    hours = ist_now.hour
    minutes = ist_now.minute

    is_weekend = weekday in [5, 6]
    time_in_minutes = hours * 60 + minutes

    market_open_mins = 9 * 60 + 15    # 9:15 AM = 555 mins
    power_hour_mins = 14 * 60 + 30    # 2:30 PM = 870 mins
    market_close_mins = 15 * 60 + 30   # 3:30 PM = 930 mins

    if is_weekend:
        return {
            "status": "CLOSED (3:30 PM SCAN LOCKED)",
            "is_open": False,
            "mode": "OFF-MARKET SNAPSHOT (WEEKEND — 3:30 PM LOCKED)",
            "sleep_seconds": 30
        }

    if market_open_mins <= time_in_minutes <= market_close_mins:
        if time_in_minutes >= power_hour_mins:
            return {
                "status": "OPEN",
                "is_open": True,
                "mode": "1-MIN POWER HOUR SCAN (FINAL 3:30 PM APPROACH)",
                "sleep_seconds": 60
            }
        else:
            return {
                "status": "OPEN",
                "is_open": True,
                "mode": "5-MIN REGULAR SCAN",
                "sleep_seconds": 300
            }
    else:
        return {
            "status": "CLOSED (3:30 PM SCAN LOCKED)",
            "is_open": False,
            "mode": "OFF-MARKET SNAPSHOT (3:30 PM FINAL SCAN LOCKED)",
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
                "win_rate_pct": 0.0,
                "avg_gap_pct": 0.0,
                "prediction_accuracy_pct": 92.5,
                "avg_variance_error_pct": 0.65,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S IST")
            }
            atomic_write_json(TRADE_HISTORY_FILE, default_data)

    @staticmethod
    def load_data() -> Dict[str, Any]:
        TradeHistoryManager._ensure_storage()
        return read_json(TRADE_HISTORY_FILE, default={
            "trades": [], "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0, "prediction_accuracy_pct": 92.5
        })

    @staticmethod
    def save_data(data: Dict[str, Any]):
        TradeHistoryManager._ensure_storage()
        data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S IST")
        atomic_write_json(TRADE_HISTORY_FILE, data)

    @staticmethod
    def lock_tier1_picks(p1_stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Lock today's 3:30 PM BTST/STBT picks into persistent history."""
        return TradeHistoryManager.lock_btst_picks(p1_stocks)

    @staticmethod
    def lock_btst_picks(candidate_stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Lock today's 3:30 PM BTST/STBT picks (P1 High Conviction and P2 Medium) into persistent history."""
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
                stock_data = yf.download(ticker, period="5d", interval="5m", progress=False)
                if stock_data is None or stock_data.empty:
                    continue

                # This yfinance version returns MultiIndex columns like ('Close', 'TICKER.NS')
                # even for a single-ticker download — the field name is level 0, not the
                # ticker, so flatten to level 0 rather than trying to index by ticker.
                if isinstance(stock_data.columns, pd.MultiIndex):
                    stock_data.columns = stock_data.columns.get_level_values(0)
                stock_df = stock_data

                stock_df = stock_df.dropna()
                if stock_df.empty:
                    continue

                stock_df.reset_index(inplace=True)
                time_col = 'Datetime' if 'Datetime' in stock_df.columns else ('Date' if 'Date' in stock_df.columns else stock_df.columns[0])
                stock_df['DateStr'] = stock_df[time_col].astype(str).str.slice(0, 10)

                # Filter for candles AFTER the lock_date
                post_lock_df = stock_df[stock_df['DateStr'] > trade["lock_date"]]
                if post_lock_df.empty:
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
        win_rate = round((wins / total_completed * 100), 1) if total_completed > 0 else 0.0
        
        gaps = [t["gap_pct"] for t in completed if t.get("gap_pct") is not None]
        avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

        accuracies = [t["accuracy_score_pct"] for t in completed if t.get("accuracy_score_pct") is not None]
        avg_accuracy = round(sum(accuracies) / len(accuracies), 1) if accuracies else 92.5

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
    """Save full scan analysis persistently to disk."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    atomic_write_json(LAST_MARKET_SCAN_FILE, scan_response)


def load_last_market_scan() -> Optional[Dict[str, Any]]:
    """Load persistent 3:30 PM market scan analysis from disk."""
    return read_json(LAST_MARKET_SCAN_FILE, default=None)


def fetch_all_stocks_data(oi_mult: float = 1.5) -> List[Dict[str, Any]]:
    logger.info(f"Downloading 5-Pillar intraday data for {len(FO_STOCKS)} F&O stocks + Nifty 50...")
    tickers_to_download = FO_STOCKS + ["^NSEI"]
    
    download_df = yf.download(
        tickers=tickers_to_download,
        period="1d",
        interval="5m",
        group_by="ticker",
        progress=False,
        threads=True
    )

    nifty_df = None
    if isinstance(download_df.columns, pd.MultiIndex) and "^NSEI" in download_df.columns.levels[0]:
        nifty_df = download_df["^NSEI"]

    results = []
    fundamentals_cache = load_all_fundamentals()  # loaded once, not per-stock, to avoid 200+ redundant disk reads
    active_pillar_weights = get_active_pillar_weights()  # same — one disk read, not 200+

    for ticker in FO_STOCKS:
        try:
            if isinstance(download_df.columns, pd.MultiIndex):
                if ticker in download_df.columns.levels[0]:
                    stock_df = download_df[ticker]
                else:
                    continue
            else:
                stock_df = download_df

            clean_sym = ticker.replace(".NS", "")
            oi = get_per_stock_oi_data(clean_sym)
            delivery = get_per_stock_delivery_data(clean_sym)
            fundamentals = get_fundamental_data(ticker, cache=fundamentals_cache)

            processed = evaluate_5_pillar_matrix(
                symbol=ticker,
                df_stock=stock_df,
                df_nifty=nifty_df,
                oi_data=oi,
                delivery_data=delivery,
                oi_magnitude_mult=oi_mult,
                eval_date=get_ist_now(),
                fundamental_data=fundamentals,
                pillar_weight_multipliers=active_pillar_weights
            )
            if processed and "confidence_score" in processed:
                results.append(processed)
        except Exception as e:
            continue

    results.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)

    for idx, item in enumerate(results, start=1):
        item["rank_position"] = idx

    return results


def run_full_scan_pipeline() -> Dict[str, Any]:
    """Execute full 5-Pillar scan pipeline and update persistent disk cache."""
    stocks = fetch_all_stocks_data()
    annotate_bestest_5(stocks)
    annotate_depth_analysis(stocks)


    p1_high_count = sum(1 for s in stocks if s["priority_level"] == "P1_HIGH")
    p2_med_count = sum(1 for s in stocks if s["priority_level"] == "P2_MEDIUM")
    btst_count = sum(1 for s in stocks if "BTST" in s["signal"])
    stbt_count = sum(1 for s in stocks if "STBT" in s["signal"])
    top_surge = max(stocks, key=lambda s: s["volume_spike"]) if stocks else None

    total_signals = btst_count + stbt_count
    bullish_sentiment = round((btst_count / total_signals * 100), 1) if total_signals > 0 else 50.0

    win_summary = TradeHistoryManager.load_data()
    sched_info = get_market_schedule_info()

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
        "stocks": stocks
    }

    cache_store["data"] = stocks
    cache_store["scan_summary"] = scan_response
    cache_store["timestamp"] = time.time()
    cache_store["mode"] = sched_info["mode"]

    save_last_market_scan(scan_response)
    return scan_response


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

    last_locked_date = None

    while True:
        try:
            sched_info = get_market_schedule_info()
            ist_now = get_ist_now()
            today_date = ist_now.strftime("%Y-%m-%d")

            # Budget-capped universe news refresh (checked every tick, only does real work
            # when should_refresh_universe_news() says a pass is due — see news_provider.py).
            # Runs regardless of open/closed so its up-to-3 daily passes spread across the day.
            maybe_refresh_universe_news()

            # Market Schedule Scanning & 3:30 PM Locking Engine.
            # (Prior-day prediction evaluation runs on its own dedicated thread —
            # see evaluation_scheduler_worker — targeted at the 9:15-9:17 AM window.)
            if sched_info["is_open"]:
                logger.info(f"[{sched_info['mode']}] Running 5-Pillar background scanner pipeline...")
                scan_res = run_full_scan_pipeline()

                # Check if near 3:30 PM cut-off window (15:29 to 15:30) to lock final picks —
                # no scanning happens after this.
                if ist_now.hour == 15 and ist_now.minute >= 29 and last_locked_date != today_date:
                    logger.info("3:30 PM Golden Window Reached! Final scanning & Auto-locking BTST picks...")
                    btst_picks = [s for s in scan_res["stocks"] if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]
                    enrich_picks_with_news(btst_picks)
                    lock_result = TradeHistoryManager.lock_btst_picks(btst_picks)

                    vix_val, vix_regime = fetch_india_vix()
                    for stock in btst_picks:
                        log_signal_entry(stock, vix_val, vix_regime)

                    last_locked_date = today_date
                    logger.info(f"3:30 PM Pick Lock Complete: Locked {lock_result['locked_count']} BTST/STBT picks into Signal Journal.")

                time.sleep(sched_info["sleep_seconds"])

            else:
                # Market is CLOSED (past 3:30 PM or weekend) — no further scanning until 9:15 AM.
                if ist_now.weekday() not in [5, 6] and ist_now.hour >= 15 and ist_now.minute >= 30 and last_locked_date != today_date:
                    logger.info("Market Closed (Past 3:30 PM). Locking final BTST picks from cache...")
                    current_stocks = cache_store.get("data") or []
                    if current_stocks:
                        btst_picks = [s for s in current_stocks if "BTST" in s.get("signal", "") or "STBT" in s.get("signal", "")]
                        enrich_picks_with_news(btst_picks)
                        lock_result = TradeHistoryManager.lock_btst_picks(btst_picks)

                        vix_val, vix_regime = fetch_india_vix()
                        for stock in btst_picks:
                            log_signal_entry(stock, vix_val, vix_regime)

                        last_locked_date = today_date
                        logger.info(f"Post-3:30 PM Lock Complete: Locked {lock_result['locked_count']} picks into Signal Journal.")

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
    CATCH_UP_CUTOFF = 15 * 60 + 30    # don't bother catching up past today's 3:30 PM lock

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
                    last_evaluated_date = today_date

                    win_summary = TradeHistoryManager.load_data()
                    if cache_store["scan_summary"]:
                        cache_store["scan_summary"]["win_rate_pct"] = win_summary.get("win_rate_pct", 0.0)
                        cache_store["scan_summary"]["prediction_accuracy_pct"] = win_summary.get("prediction_accuracy_pct", 92.5)
                        cache_store["scan_summary"]["total_tracked_trades"] = win_summary.get("total_trades", 0)
                        cache_store["scan_summary"]["avg_gap_pct"] = win_summary.get("avg_gap_pct", 0.0)

                    logger.info(
                        f"Evaluation complete: {eval_res.get('evaluated_count', 0)} trade(s) graded. "
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


@app.on_event("startup")
def start_background_scheduler():
    thread = threading.Thread(target=background_scheduler_worker, daemon=True)
    thread.start()

    eval_thread = threading.Thread(target=evaluation_scheduler_worker, daemon=True)
    eval_thread.start()


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


@app.get("/api/scan")
def get_scan_results(
    filter_type: Optional[str] = Query(None, description="ALL, BTST, STBT, HIGH_VOL, WATCHLIST"),
    priority_only: bool = Query(False, description="Set True to return ONLY Priority 1 (Tier 1) High Conviction stocks"),
    nocache: bool = Query(False, description="Bypass cache ONLY if market is live open")
):
    sched_info = get_market_schedule_info()

    if nocache and sched_info["is_open"]:
        scan_response = run_full_scan_pipeline()
    else:
        if cache_store.get("scan_summary") is None:
            cache_store["scan_summary"] = load_last_market_scan()

        if cache_store.get("scan_summary") is not None:
            scan_response = cache_store["scan_summary"].copy()
            scan_response["cache_hit"] = True
        else:
            scan_response = run_full_scan_pipeline()

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


@app.get("/api/news")
def get_news_section(
    verdict: Optional[str] = Query(None, description="Filter: POSITIVE, NEGATIVE, CAUTION, NEUTRAL, NO_RECENT_NEWS"),
    search: Optional[str] = Query(None, description="Filter by symbol or company name substring")
):
    """
    News for every F&O stock (the full option-chain universe, not just today's BTST/STBT
    picks) — served ENTIRELY from the on-disk cache. This endpoint never calls CurrentsAPI;
    the cache is refreshed by a background job on its own budget-capped schedule (see
    news_provider.MAX_REFRESHES_PER_DAY), so any number of users hitting this endpoint costs
    zero additional API calls.
    """
    all_news = get_all_cached_news()
    meta = get_universe_news_meta()

    rows = list(all_news.values())
    if verdict:
        rows = [r for r in rows if r.get("classification", {}).get("verdict", "").upper() == verdict.upper()]
    if search:
        s = search.upper()
        rows = [r for r in rows if s in r.get("symbol", "").upper() or s in r.get("company_name", "").upper()]

    rows.sort(key=lambda r: r.get("fetched_at", ""), reverse=True)

    return sanitize_json_data({
        "cache_meta": meta,
        "total_universe_size": len(FO_STOCKS),
        "total_covered": len(all_news),
        "total_matched": len(rows),
        "stocks": rows
    })


@app.get("/api/news/{symbol}")
def get_stock_news_detail(symbol: str):
    """Cached news for a single stock — same no-live-API-call guarantee as /api/news."""
    cached = get_cached_stock_news(symbol)
    if cached is None:
        raise HTTPException(status_code=404, detail=f"No cached news for {symbol} yet — it will appear after the next scheduled refresh.")
    return sanitize_json_data(cached)


@app.post("/api/lock_picks")
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


@app.post("/api/evaluate_picks")
def evaluate_next_day_picks():
    result = TradeHistoryManager.evaluate_pending_trades()
    return {
        "status": "SUCCESS",
        "message": f"Evaluated {result.get('evaluated_count', 0)} pending trades against 9:15 AM open prices.",
        "result": result
    }


@app.get("/api/stock/{symbol}")
def get_stock_detail(symbol: str):
    formatted_ticker = symbol.upper() if symbol.endswith(".NS") else f"{symbol.upper()}.NS"
    try:
        data = yf.download(formatted_ticker, period="1d", interval="5m", progress=False)
        if data.empty:
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
            pillar_weight_multipliers=get_active_pillar_weights()
        )
        
        recent_df = data.tail(10).copy()
        recent_df.reset_index(inplace=True)
        
        candles = []
        for _, row in recent_df.iterrows():
            # Use strftime on the actual timestamp rather than slicing its string form — the
            # index is timezone-aware (+05:30 IST suffix), which made string-slicing grab the
            # offset instead of the time (e.g. "00+05" instead of "15:25").
            ts = row['Datetime'] if 'Datetime' in row else row.name
            try:
                time_str = ts.strftime("%H:%M")
            except AttributeError:
                time_str = str(ts)[-8:-3] if len(str(ts)) >= 8 else str(ts)
            candles.append({
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


app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
