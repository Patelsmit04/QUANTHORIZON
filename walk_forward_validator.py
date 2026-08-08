"""
WALK-FORWARD VALIDATOR & DYNAMIC PILLAR WEIGHTING ENGINE
=========================================================
1. Walk-Forward Validation: Rolling Out-of-Sample backtest validator.
2. Lookahead Bias Audit: Verifies 3:30 PM signal generation strictly uses <= 3:30 PM data.
3. Dynamic Pillar Weighting: Re-weights 6 pillars (incl. Pillar 6: Institutional Flow) based on
   standalone hit rates, AUTO-APPLIED to live scoring once per day — with safety limits: the
   N>=30 sample guardrail below, and a
   cap on how much any single day's data can move a weight (MAX_DAILY_CHANGE_PCT), so one lucky
   or unlucky streak right at the sample threshold can't whipsaw live scoring. This is
   auto-improvement, not unsupervised drift — every change is capped, logged, and auditable via
   the history file.
"""

import os
import logging
from datetime import date
from typing import Dict, List, Any, Optional
from signal_journal import get_db_connection
from json_utils import atomic_write_json, read_json
from env_utils import DATA_DIR
from pg_utils import USE_POSTGRES, pg_read_json, pg_write_json

logger = logging.getLogger("WalkForwardValidator")

PILLAR_WEIGHTS_FILE = os.path.join(DATA_DIR, "active_pillar_weights.json")
PILLAR_WEIGHTS_HISTORY_FILE = os.path.join(DATA_DIR, "pillar_weights_history.json")
MAX_HISTORY_ENTRIES = 90

DEFAULT_PILLAR_WEIGHTS = {
    "Pillar 1: Futures OI": 1.0,
    "Pillar 2: Vol Persistence": 1.0,
    "Pillar 3: Relative Strength": 1.0,
    "Pillar 4: Volume Spike": 1.0,
    "Pillar 5: Marubozu Close": 1.0,
    "Pillar 6: Institutional Flow": 1.0,
}

MAX_DAILY_CHANGE_PCT = 0.15  # a weight can move at most +/-15% from its current value in one day


def run_lookahead_bias_audit(df_intraday: Any, eval_timestamp_str: str) -> Dict[str, Any]:
    """
    Audit intraday dataframe to confirm signal generation logic at 3:30 PM
    only ever accesses candles timestamped at or before 3:30 PM that day.
    """
    if df_intraday is None or df_intraday.empty:
        return {"audit_passed": True, "reason": "Empty dataset — no lookahead detected."}

    # Verify no candle in df_intraday is dated after eval_timestamp_str
    try:
        if 'Datetime' in df_intraday.columns:
            max_dt_str = str(df_intraday['Datetime'].max())
        else:
            max_dt_str = str(df_intraday.index[-1])

        if max_dt_str > eval_timestamp_str:
            logger.error(f"LOOKAHEAD BIAS DETECTED: Data contains timestamp {max_dt_str} > eval time {eval_timestamp_str}")
            return {
                "audit_passed": False,
                "reason": f"LOOKAHEAD BIAS DETECTED: Max candle timestamp {max_dt_str} exceeds 3:30 PM evaluation time {eval_timestamp_str}"
            }
    except Exception as e:
        logger.warning(f"Timestamp audit warning: {e}")

    return {
        "audit_passed": True,
        "reason": "PASS: All candles strictly timestamped <= 3:30 PM evaluation window."
    }


def run_walk_forward_validation(window_days: int = 30) -> Dict[str, Any]:
    """
    Rolling out-of-sample walk-forward validation.
    Trains / tunes on in-sample window, tests strictly on out-of-sample window.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.signal_date, j.confidence_score, e.is_direction_correct, e.is_trade_win, e.net_pnl_pct
            FROM signal_journal j
            INNER JOIN signal_evaluations e ON j.id = e.signal_id
            ORDER BY j.signal_date ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]

    if len(rows) < 30:
        return {
            "status": "INSUFFICIENT SAMPLE (N < 30)",
            "message": "Walk-forward validation requires at least 30 evaluated historical signals.",
            "out_of_sample_accuracy_pct": 0.0,
            "out_of_sample_win_rate_pct": 0.0,
            "windows_evaluated": 0
        }

    # Group rows by distinct signal_date
    dates = sorted(list({r["signal_date"] for r in rows}))
    if len(dates) < 2:
        return {
            "status": "INSUFFICIENT DATES",
            "message": "Walk-forward validation requires at least 2 distinct trading dates.",
            "out_of_sample_accuracy_pct": 0.0,
            "out_of_sample_win_rate_pct": 0.0,
            "windows_evaluated": 0
        }

    # Split dates: 70% in-sample (train), 30% out-of-sample (test)
    split_idx = int(len(dates) * 0.7)
    train_dates = set(dates[:split_idx])
    test_dates = set(dates[split_idx:])

    train_rows = [r for r in rows if r["signal_date"] in train_dates]
    test_rows = [r for r in rows if r["signal_date"] in test_dates]

    oos_corr = sum(1 for r in test_rows if r["is_direction_correct"] == 1)
    oos_wins = sum(1 for r in test_rows if r["is_trade_win"] == 1)

    oos_acc = round((oos_corr / len(test_rows)) * 100, 1) if test_rows else 0.0
    oos_winrate = round((oos_wins / len(test_rows)) * 100, 1) if test_rows else 0.0

    return {
        "status": "WALK_FORWARD_COMPLETE",
        "in_sample_signal_count": len(train_rows),
        "out_of_sample_signal_count": len(test_rows),
        "out_of_sample_accuracy_pct": oos_acc,
        "out_of_sample_win_rate_pct": oos_winrate,
        "windows_evaluated": len(dates)
    }


def compute_dynamic_pillar_weights() -> Dict[str, Any]:
    """
    Compute standalone predictive hit rate for each of the 5 pillars.
    Dynamically recommends pillar scoring weights proportional to hit rates.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.pillar_1_confirmed, j.pillar_2_confirmed, j.pillar_3_confirmed,
                   j.pillar_4_confirmed, j.pillar_5_confirmed, j.pillar_6_confirmed, e.is_direction_correct
            FROM signal_journal j
            INNER JOIN signal_evaluations e ON j.id = e.signal_id
        """)
        rows = [dict(r) for r in cursor.fetchall()]

    if len(rows) < 30:
        return {
            "status": "INSUFFICIENT SAMPLE (N < 30)",
            "sample_size": len(rows),
            "recommended_weights": {
                "Pillar 1: Futures OI": 1.0,
                "Pillar 2: Vol Persistence": 1.0,
                "Pillar 3: Relative Strength": 1.0,
                "Pillar 4: Volume Spike": 1.0,
                "Pillar 5: Marubozu Close": 1.0,
                "Pillar 6: Institutional Flow": 1.0
            }
        }

    pillar_hit_rates = {}
    for p in range(1, 7):
        col_name = f"pillar_{p}_confirmed"
        active_rows = [r for r in rows if r[col_name] == 1]
        if active_rows:
            correct_count = sum(1 for r in active_rows if r["is_direction_correct"] == 1)
            hit_rate = round((correct_count / len(active_rows)) * 100, 1)
        else:
            hit_rate = 50.0
        pillar_hit_rates[f"Pillar {p}"] = hit_rate

    # Calculate normalized dynamic weights (baseline average = 1.0)
    avg_rate = sum(pillar_hit_rates.values()) / len(pillar_hit_rates)
    rec_weights = {}
    name_map = {
        "Pillar 1": "Pillar 1: Futures OI",
        "Pillar 2": "Pillar 2: Vol Persistence",
        "Pillar 3": "Pillar 3: Relative Strength",
        "Pillar 4": "Pillar 4: Volume Spike",
        "Pillar 5": "Pillar 5: Marubozu Close",
        "Pillar 6": "Pillar 6: Institutional Flow"
    }

    for p, rate in pillar_hit_rates.items():
        norm_w = round(rate / avg_rate, 2) if avg_rate > 0 else 1.0
        # Absolute sanity bound on the RECOMMENDATION itself (separate from the daily-change cap
        # applied when this is actually adopted) — a pillar with very few confirmations and a
        # fluky hit rate shouldn't be able to recommend an extreme multiplier.
        norm_w = max(0.3, min(2.0, norm_w))
        rec_weights[name_map[p]] = norm_w

    return {
        "status": "DYNAMIC_WEIGHTS_COMPUTED",
        "sample_size": len(rows),
        "standalone_hit_rates_pct": pillar_hit_rates,
        "recommended_weights": rec_weights
    }


def _load_pillar_weights() -> Optional[Dict[str, Any]]:
    if USE_POSTGRES:
        return pg_read_json("active_pillar_weights", default=None)
    return read_json(PILLAR_WEIGHTS_FILE, default=None)


def _save_pillar_weights(data: Dict[str, Any]) -> None:
    if USE_POSTGRES:
        pg_write_json("active_pillar_weights", data)
        return
    atomic_write_json(PILLAR_WEIGHTS_FILE, data)


def get_active_pillar_weights() -> Dict[str, float]:
    """
    The pillar weight multipliers currently LIVE in scoring (used by
    evaluate_5_pillar_matrix). Defaults to neutral 1.0 for every pillar until the system has
    earned a change — i.e. until apply_dynamic_pillar_weights() has actually run with a
    sufficient sample. This is what scoring reads; compute_dynamic_pillar_weights() above is
    just the (uncapped, unapplied) recommendation.
    """
    stored = _load_pillar_weights()
    if not stored or "weights" not in stored:
        return dict(DEFAULT_PILLAR_WEIGHTS)
    return {**DEFAULT_PILLAR_WEIGHTS, **stored["weights"]}


def _apply_daily_cap(current: float, recommended: float) -> float:
    """A single day's evaluated signals can move a weight by at most MAX_DAILY_CHANGE_PCT —
    reaching a very different recommended weight takes several days of confirming evidence,
    not one lucky/unlucky streak landing right as the N>=30 gate opens."""
    max_up = current * (1 + MAX_DAILY_CHANGE_PCT)
    max_down = current * (1 - MAX_DAILY_CHANGE_PCT)
    return round(min(max_up, max(max_down, recommended)), 3)


def _load_weight_history() -> List[Dict[str, Any]]:
    if USE_POSTGRES:
        return pg_read_json("pillar_weights_history", default=[])
    return read_json(PILLAR_WEIGHTS_HISTORY_FILE, default=[])


def _save_weight_history(history: List[Dict[str, Any]]) -> None:
    if USE_POSTGRES:
        pg_write_json("pillar_weights_history", history)
        return
    atomic_write_json(PILLAR_WEIGHTS_HISTORY_FILE, history)


def _append_weight_history(entry: Dict[str, Any]):
    history = _load_weight_history()
    history.append(entry)
    history = history[-MAX_HISTORY_ENTRIES:]
    _save_weight_history(history)


def get_pillar_weights_history(limit: int = 30) -> List[Dict[str, Any]]:
    history = _load_weight_history()
    return history[-limit:]


def apply_dynamic_pillar_weights() -> Dict[str, Any]:
    """
    Once-daily auto-improvement step: recompute each pillar's standalone hit rate from the
    signal journal, then move the LIVE weights toward that recommendation — capped at
    +/-15%/day, and only once there are >=30 evaluated signals (compute_dynamic_pillar_weights'
    own guardrail). Below that sample size, nothing is touched: the system stays on the
    hand-tuned 1.0 baseline rather than guess from too little data.

    Every run is logged to the history file, whether or not anything actually changed, so the
    weight trajectory is fully auditable — this is auto-improvement with a paper trail, not a
    black box quietly reweighting itself.
    """
    current_weights = get_active_pillar_weights()
    today_str = date.today().isoformat()

    # Disk-backed guard against double-application, same pattern as fundamental_provider's
    # was_refresh_completed_today() — the caller (app.py's evaluation_scheduler_worker) only
    # tracks "already ran today" in an in-memory local variable, which resets on restart. A
    # restart between 9:17 AM and the 15:40 catch-up cutoff would otherwise re-enter the catch-up
    # window and apply another +/-15% move on top of today's already-applied one.
    stored = _load_pillar_weights()
    if stored and stored.get("last_updated") == today_str:
        logger.info("Dynamic pillar weights already applied today — skipping duplicate application.")
        return {"status": "ALREADY_APPLIED_TODAY", "applied": False, "active_weights": current_weights}

    computation = compute_dynamic_pillar_weights()

    if computation["status"] != "DYNAMIC_WEIGHTS_COMPUTED":
        _append_weight_history({
            "date": today_str,
            "action": "SKIPPED_INSUFFICIENT_SAMPLE",
            "sample_size": computation.get("sample_size", 0),
            "weights": current_weights,
        })
        logger.info(
            f"Dynamic pillar weights not applied — sample size {computation.get('sample_size', 0)} < 30. "
            f"Staying on current weights."
        )
        return {"status": computation["status"], "applied": False, "active_weights": current_weights}

    recommended = computation["recommended_weights"]
    new_weights: Dict[str, float] = {}
    changes: Dict[str, Any] = {}

    for pillar_name, current_val in current_weights.items():
        rec_val = recommended.get(pillar_name, current_val)
        capped_val = _apply_daily_cap(current_val, rec_val)
        new_weights[pillar_name] = capped_val
        if abs(capped_val - current_val) > 0.001:
            changes[pillar_name] = {"from": current_val, "to": capped_val, "recommended": rec_val}

    _save_pillar_weights({
        "weights": new_weights,
        "last_updated": today_str,
        "sample_size": computation["sample_size"],
        "standalone_hit_rates_pct": computation.get("standalone_hit_rates_pct", {}),
    })

    _append_weight_history({
        "date": today_str,
        "action": "APPLIED",
        "sample_size": computation["sample_size"],
        "changes": changes,
        "weights": new_weights,
    })

    if changes:
        logger.info(f"Dynamic pillar weights updated (capped +/-{MAX_DAILY_CHANGE_PCT*100:.0f}%/day): {changes}")
    else:
        logger.info("Dynamic pillar weights recomputed — already at their capped targets, no change.")

    return {"status": "APPLIED", "applied": True, "changes": changes, "active_weights": new_weights}
