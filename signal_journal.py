"""
BTST SIGNAL JOURNAL & ADVANCED METRICS ENGINE (SQLite)
======================================================
Stores persistent signal logs, next-day evaluation outcomes, simulated option P&L
(with 3.0% bid-ask spread haircut & 15-min exit rule), directional accuracy,
spread-adjusted win rate, precision (CALL/PUT), expectancy, profit factor,
confidence calibration, and sample size guardrails (N < 30).
"""

import os
import sqlite3
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import yfinance as yf

logger = logging.getLogger("SignalJournal")

DATA_DIR = "data"
DB_FILE = os.path.join(DATA_DIR, "signal_journal.db")


def get_db_connection():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_journal_db():
    """Initialize SQLite tables for Signal Journal & Evaluations."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Table 1: Signal Journal (Daily 3:30 PM Signals)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS signal_journal (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            raw_ticker TEXT NOT NULL,
            liquidity_tier TEXT NOT NULL,
            priority_level TEXT NOT NULL,
            signal TEXT NOT NULL,
            predicted_direction TEXT NOT NULL,
            option_type TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            confidence_bucket TEXT NOT NULL,
            close_price_325 REAL NOT NULL,
            predicted_gap_pct REAL NOT NULL,
            vwap REAL NOT NULL,
            volume_spike REAL NOT NULL,
            rsi REAL NOT NULL,
            range_position_pct REAL NOT NULL,
            pillar_1_confirmed INTEGER NOT NULL,
            pillar_1_weight REAL NOT NULL,
            pillar_2_confirmed INTEGER NOT NULL,
            pillar_2_weight REAL NOT NULL,
            pillar_3_confirmed INTEGER NOT NULL,
            pillar_3_weight REAL NOT NULL,
            pillar_4_confirmed INTEGER NOT NULL,
            pillar_4_weight REAL NOT NULL,
            pillar_5_confirmed INTEGER NOT NULL,
            pillar_5_weight REAL NOT NULL,
            total_pillar_weight REAL NOT NULL,
            expiry_discount_applied INTEGER NOT NULL,
            vix_regime TEXT NOT NULL,
            vix_value REAL NOT NULL
        );
        """)

        # Table 2: Signal Evaluations (Next-Day Outcomes & P&L)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS signal_evaluations (
            signal_id TEXT PRIMARY KEY,
            eval_date TEXT NOT NULL,
            eval_timestamp TEXT NOT NULL,
            next_open_915 REAL NOT NULL,
            next_high REAL,
            next_low REAL,
            next_close_930 REAL,
            actual_gap_pct REAL NOT NULL,
            is_direction_correct INTEGER NOT NULL,
            variance_error_pct REAL NOT NULL,
            directional_accuracy_score REAL NOT NULL,
            trade_taken INTEGER NOT NULL,
            est_entry_premium REAL NOT NULL,
            est_exit_premium REAL NOT NULL,
            spread_haircut_pct REAL NOT NULL,
            gross_pnl_pct REAL NOT NULL,
            net_pnl_pct REAL NOT NULL,
            is_trade_win INTEGER NOT NULL,
            FOREIGN KEY(signal_id) REFERENCES signal_journal(id)
        );
        """)
        conn.commit()
    logger.info("Signal Journal SQLite DB initialized successfully.")


# Initialize schema on module import
init_journal_db()


def derive_confidence_bucket(score: int) -> str:
    """Categorize confidence score into standard calibration buckets."""
    if score >= 90:
        return "90-100"
    elif score >= 80:
        return "80-89"
    elif score >= 70:
        return "70-79"
    else:
        return "<70"


def log_signal_entry(stock: Dict[str, Any], vix_value: float = 15.0, vix_regime: str = "NORMAL") -> bool:
    """Log a single stock signal into SQLite Signal Journal."""
    today_date = datetime.now().strftime("%Y-%m-%d")
    signal_id = f"{today_date}_{stock['symbol']}"

    signal_text = stock.get("signal", "NEUTRAL")
    pred_direction = "BULLISH" if "BTST" in signal_text else ("BEARISH" if "STBT" in signal_text else "NEUTRAL")
    conf_score = int(stock.get("confidence_score", 50))
    conf_bucket = derive_confidence_bucket(conf_score)

    pw = stock.get("pillar_weights", {})
    p1_w = float(pw.get("Pillar 1: Futures OI", 0.0))
    p2_w = float(pw.get("Pillar 2: Vol Persistence", 0.0))
    p3_w = float(pw.get("Pillar 3: Relative Strength", 0.0))
    p4_w = float(pw.get("Pillar 4: Volume Spike", 0.0))
    p5_w = float(pw.get("Pillar 5: Marubozu Close", 0.0))

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR IGNORE INTO signal_journal (
                id, timestamp, signal_date, symbol, raw_ticker, liquidity_tier,
                priority_level, signal, predicted_direction, option_type,
                confidence_score, confidence_bucket, close_price_325, predicted_gap_pct,
                vwap, volume_spike, rsi, range_position_pct,
                pillar_1_confirmed, pillar_1_weight, pillar_2_confirmed, pillar_2_weight,
                pillar_3_confirmed, pillar_3_weight, pillar_4_confirmed, pillar_4_weight,
                pillar_5_confirmed, pillar_5_weight, total_pillar_weight,
                expiry_discount_applied, vix_regime, vix_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_id,
                time.strftime("%Y-%m-%d %H:%M:%S IST"),
                today_date,
                stock["symbol"],
                stock["raw_ticker"],
                stock.get("liquidity_tier", "TIER_1"),
                stock.get("priority_level", "P1_HIGH"),
                signal_text,
                pred_direction,
                stock.get("option_type", "NONE"),
                conf_score,
                conf_bucket,
                float(stock.get("ltp", 0.0)),
                float(stock.get("predicted_gap_pct", 0.0)),
                float(stock.get("vwap", 0.0)),
                float(stock.get("volume_spike", 1.0)),
                float(stock.get("rsi", 50.0)),
                float(stock.get("range_position_pct", 50.0)),
                1 if p1_w > 0 else 0, p1_w,
                1 if p2_w > 0 else 0, p2_w,
                1 if p3_w > 0 else 0, p3_w,
                1 if p4_w > 0 else 0, p4_w,
                1 if p5_w > 0 else 0, p5_w,
                float(stock.get("confirmed_pillars_weight", 0.0)),
                1 if stock.get("expiry_discount_applied", False) else 0,
                vix_regime,
                vix_value
            ))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error logging signal {signal_id}: {e}")
        return False


def evaluate_pending_signals() -> Dict[str, Any]:
    """
    Fetch 9:15 AM open and 9:30 AM close prices to evaluate directional accuracy
    and simulated option trade P&L (with 3.0% bid-ask spread haircut).
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.* FROM signal_journal j
            LEFT JOIN signal_evaluations e ON j.id = e.signal_id
            WHERE e.signal_id IS NULL AND j.signal != 'NEUTRAL'
        """)
        unevaluated = [dict(row) for row in cursor.fetchall()]

    if not unevaluated:
        return {"evaluated_count": 0, "message": "No pending signals to evaluate."}

    evaluated_count = 0
    today_date_str = datetime.now().strftime("%Y-%m-%d")

    for sig in unevaluated:
        # Skip signals generated today before market opens tomorrow
        if sig["signal_date"] == today_date_str:
            continue

        ticker = sig["raw_ticker"]
        try:
            df = yf.download(ticker, period="5d", interval="5m", progress=False)
            if df is None or df.empty:
                continue

            # This yfinance version returns MultiIndex columns like ('Close', 'TICKER.NS')
            # even for a single-ticker download — the field name is level 0, not the ticker,
            # so flatten to level 0 rather than trying to index by ticker.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            stock_df = df

            stock_df = stock_df.dropna().copy()
            if stock_df.empty:
                continue

            stock_df.reset_index(inplace=True)
            time_col = 'Datetime' if 'Datetime' in stock_df.columns else ('Date' if 'Date' in stock_df.columns else stock_df.columns[0])
            stock_df['DateStr'] = stock_df[time_col].astype(str).str.slice(0, 10)

            post_lock_df = stock_df[stock_df['DateStr'] > sig["signal_date"]]
            if post_lock_df.empty:
                continue

            open_915 = float(post_lock_df.iloc[0]['Open'])
            close_325 = float(sig["close_price_325"])
            
            # Get 9:30 AM price (3rd 5-min candle of the day, index 2 or 3)
            exit_candle_idx = min(3, len(post_lock_df) - 1)
            close_930 = float(post_lock_df.iloc[exit_candle_idx]['Close'])
            high_day = float(post_lock_df['High'].max())
            low_day = float(post_lock_df['Low'].min())

            if close_325 <= 0 or open_915 <= 0:
                continue

            actual_gap = round(((open_915 - close_325) / close_325) * 100, 2)
            predicted_gap = float(sig["predicted_gap_pct"])
            pred_direction = sig["predicted_direction"]

            # Directional Accuracy check
            is_dir_correct = 0
            if pred_direction == "BULLISH" and actual_gap > 0:
                is_dir_correct = 1
            elif pred_direction == "BEARISH" and actual_gap < 0:
                is_dir_correct = 1

            variance_err = round(abs(actual_gap - predicted_gap), 2)
            acc_score = max(0.0, round(100.0 - (variance_err * 15.0), 1))

            # SIMULATED OPTIONS TRADE P&L (15-Min Exit Rule at 9:30 AM with 3.0% Spread Haircut)
            trade_taken = 1 if sig["priority_level"] in ["P1_HIGH", "P2_MEDIUM"] else 0
            spread_haircut = 3.0  # 3% haircut on entry and exit
            
            # Premium estimation: ~1.5% of spot price
            est_entry_premium = max(1.0, open_915 * 0.015)
            
            if pred_direction == "BULLISH":
                # CALL option gain tracking spot delta
                spot_delta = close_930 - open_915
                est_exit_premium = max(0.1, est_entry_premium + spot_delta)
            else:
                # PUT option gain tracking inverse spot delta
                spot_delta = open_915 - close_930
                est_exit_premium = max(0.1, est_entry_premium + spot_delta)

            gross_pnl = round(((est_exit_premium - est_entry_premium) / est_entry_premium) * 100, 2)
            net_pnl = round(gross_pnl - (2 * spread_haircut), 2)
            is_win = 1 if net_pnl > 0 else 0

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR REPLACE INTO signal_evaluations (
                    signal_id, eval_date, eval_timestamp, next_open_915, next_high, next_low,
                    next_close_930, actual_gap_pct, is_direction_correct, variance_error_pct,
                    directional_accuracy_score, trade_taken, est_entry_premium, est_exit_premium,
                    spread_haircut_pct, gross_pnl_pct, net_pnl_pct, is_trade_win
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sig["id"],
                    today_date_str,
                    time.strftime("%Y-%m-%d %H:%M:%S IST"),
                    round(open_915, 2),
                    round(high_day, 2),
                    round(low_day, 2),
                    round(close_930, 2),
                    actual_gap,
                    is_dir_correct,
                    variance_err,
                    acc_score,
                    trade_taken,
                    round(est_entry_premium, 2),
                    round(est_exit_premium, 2),
                    spread_haircut,
                    gross_pnl,
                    net_pnl,
                    is_win
                ))
                conn.commit()
                evaluated_count += 1
                logger.info(f"Journal Evaluated {sig['symbol']}: Dir Correct={is_dir_correct}, Gap={actual_gap}%, Net PnL={net_pnl}% (Win={is_win})")

        except Exception as e:
            logger.warning(f"Error evaluating journal entry for {ticker}: {e}")

    return {"evaluated_count": evaluated_count}


def get_metrics_summary() -> Dict[str, Any]:
    """
    Calculate full Part 1 Metrics: Directional Accuracy, Win Rate, CALL/PUT Precision,
    Expectancy, Profit Factor, VIX Regime breakdown, and Sample Size Guardrails.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.*, e.* FROM signal_journal j
            INNER JOIN signal_evaluations e ON j.id = e.signal_id
        """)
        rows = [dict(r) for r in cursor.fetchall()]

    total_evaluated = len(rows)
    sample_guardrail = total_evaluated < 30
    sample_guardrail_msg = "INSUFFICIENT SAMPLE (N < 30)" if sample_guardrail else "SUFFICIENT SAMPLE (N >= 30)"

    if total_evaluated == 0:
        return {
            "total_evaluated_signals": 0,
            "sample_guardrail": sample_guardrail_msg,
            "directional_accuracy_pct": 0.0,
            "win_rate_pct": 0.0,
            "call_precision_pct": 0.0,
            "put_precision_pct": 0.0,
            "expectancy_pct": 0.0,
            "profit_factor": 0.0,
            "vix_regime_breakdown": {}
        }

    # 1. Directional Accuracy
    correct_direction_count = sum(1 for r in rows if r["is_direction_correct"] == 1)
    directional_accuracy = round((correct_direction_count / total_evaluated) * 100, 1)

    # 2. Win Rate (Executed Trades)
    trades = [r for r in rows if r["trade_taken"] == 1]
    total_trades = len(trades)
    winning_trades = [t for t in trades if t["is_trade_win"] == 1]
    losing_trades = [t for t in trades if t["is_trade_win"] == 0]
    win_rate = round((len(winning_trades) / total_trades) * 100, 1) if total_trades > 0 else 0.0

    # 3. Precision (CALL vs PUT)
    call_signals = [r for r in rows if r["option_type"] == "CALL (CE)"]
    put_signals = [r for r in rows if r["option_type"] == "PUT (PE)"]

    call_precision = round((sum(1 for r in call_signals if r["is_direction_correct"] == 1) / len(call_signals) * 100), 1) if call_signals else 0.0
    put_precision = round((sum(1 for r in put_signals if r["is_direction_correct"] == 1) / len(put_signals) * 100), 1) if put_signals else 0.0

    # 4. Expectancy Per Trade = (Win Rate * Avg Win %) - (Loss Rate * Avg Loss %)
    avg_win = round(sum(t["net_pnl_pct"] for t in winning_trades) / len(winning_trades), 2) if winning_trades else 0.0
    avg_loss = round(abs(sum(t["net_pnl_pct"] for t in losing_trades) / len(losing_trades)), 2) if losing_trades else 0.0
    
    win_rate_dec = win_rate / 100.0
    loss_rate_dec = (100.0 - win_rate) / 100.0 if total_trades > 0 else 0.0
    expectancy = round((win_rate_dec * avg_win) - (loss_rate_dec * avg_loss), 2)

    # 5. Profit Factor = Total Gains / Total Losses
    total_gains = sum(t["net_pnl_pct"] for t in winning_trades)
    total_losses = abs(sum(t["net_pnl_pct"] for t in losing_trades))
    profit_factor = round(total_gains / total_losses, 2) if total_losses > 0 else (99.9 if total_gains > 0 else 0.0)

    # 6. VIX Regime Breakdown
    vix_regimes = {}
    for regime in ["LOW_VOL", "NORMAL", "HIGH_VOL"]:
        reg_rows = [r for r in rows if r["vix_regime"] == regime]
        if reg_rows:
            reg_corr = sum(1 for r in reg_rows if r["is_direction_correct"] == 1)
            reg_trades = [r for r in reg_rows if r["trade_taken"] == 1]
            reg_wins = sum(1 for r in reg_trades if r["is_trade_win"] == 1)
            vix_regimes[regime] = {
                "count": len(reg_rows),
                "sample_status": "SUFFICIENT" if len(reg_rows) >= 30 else "INSUFFICIENT SAMPLE (<30)",
                "directional_accuracy_pct": round((reg_corr / len(reg_rows)) * 100, 1),
                "win_rate_pct": round((reg_wins / len(reg_trades)) * 100, 1) if reg_trades else 0.0
            }
        else:
            vix_regimes[regime] = {"count": 0, "sample_status": "NO DATA", "directional_accuracy_pct": 0.0, "win_rate_pct": 0.0}

    return {
        "total_evaluated_signals": total_evaluated,
        "total_executed_trades": total_trades,
        "sample_guardrail": sample_guardrail_msg,
        "directional_accuracy_pct": directional_accuracy,
        "win_rate_pct": win_rate,
        "call_precision_pct": call_precision,
        "put_precision_pct": put_precision,
        "avg_win_pnl_pct": avg_win,
        "avg_loss_pnl_pct": avg_loss,
        "expectancy_pnl_pct": expectancy,
        "profit_factor": profit_factor,
        "vix_regime_breakdown": vix_regimes
    }


def get_confidence_calibration() -> List[Dict[str, Any]]:
    """
    Build Confidence Calibration table by score buckets (90-100, 80-89, 70-79, <70).
    Checks if higher confidence correlates with higher real win rates.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.confidence_bucket, j.confidence_score, e.is_direction_correct, e.is_trade_win, e.trade_taken
            FROM signal_journal j
            INNER JOIN signal_evaluations e ON j.id = e.signal_id
        """)
        rows = [dict(r) for r in cursor.fetchall()]

    buckets = ["90-100", "80-89", "70-79", "<70"]
    calibration = []

    for bucket in buckets:
        b_rows = [r for r in rows if r["confidence_bucket"] == bucket]
        count = len(b_rows)
        sample_status = "SUFFICIENT" if count >= 30 else "INSUFFICIENT SAMPLE (<30)"
        
        if count > 0:
            corr = sum(1 for r in b_rows if r["is_direction_correct"] == 1)
            b_trades = [r for r in b_rows if r["trade_taken"] == 1]
            wins = sum(1 for r in b_trades if r["is_trade_win"] == 1)
            dir_acc = round((corr / count) * 100, 1)
            win_rate = round((wins / len(b_trades)) * 100, 1) if b_trades else 0.0
        else:
            dir_acc = 0.0
            win_rate = 0.0

        calibration.append({
            "confidence_bucket": bucket,
            "total_signals": count,
            "sample_status": sample_status,
            "directional_accuracy_pct": dir_acc,
            "win_rate_pct": win_rate
        })

    return calibration
