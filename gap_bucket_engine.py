"""
PROBABILITY-BUCKETED GAP FORECAST ENGINE
========================================
Calculates probability distribution across 4 overnight gap buckets:
0-1%, 1-2%, 2-3%, 3%+

Uses historical analog matching over evaluated signals in signal_journal
to ground bucket probabilities in real past performance data.

When insufficient historical data exists (< MIN_SAMPLE_THRESHOLD evaluated
analogs), produces a model-estimated distribution that varies meaningfully
by ticker, confidence score, predicted gap, and signal direction — and
explicitly marks the result as non-empirical so the frontend can label it
honestly as "Preliminary."
"""

import math
import hashlib
import logging
from typing import Dict, Any, Optional
from signal_journal import get_db_connection

logger = logging.getLogger("GapBucketEngine")

# --- Configuration -----------------------------------------------------------
GAP_BUCKETS = ["0-1%", "1-2%", "2-3%", "3%+"]
MIN_SAMPLE_THRESHOLD = 20  # Below this, distributions are model-estimated


# --- Bucket classification ----------------------------------------------------
def classify_gap_into_bucket(actual_gap_pct: float) -> str:
    """Classify a realized gap percentage into one of the 4 discrete buckets."""
    abs_gap = abs(actual_gap_pct)
    if abs_gap < 1.0:
        return "0-1%"
    elif abs_gap < 2.0:
        return "1-2%"
    elif abs_gap < 3.0:
        return "2-3%"
    else:
        return "3%+"


def _ticker_hash_float(symbol: str, salt: str = "") -> float:
    """
    Produce a deterministic float in [0, 1) from a ticker symbol.
    Used to add per-ticker jitter so no two tickers produce byte-identical
    model-estimated distributions, even when their confidence/gap are close.
    """
    h = hashlib.sha256(f"{symbol}:{salt}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


# --- Main entry point ---------------------------------------------------------
def calculate_gap_bucket_distribution(
    confidence_score: int,
    predicted_gap_pct: float,
    symbol: Optional[str] = None,
    signal_direction: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute probability distribution for overnight gap landing in each bucket.

    1. Tries ticker-specific empirical data first (same ticker, same direction,
       similar confidence band).
    2. Falls back to direction+confidence-band analogs across all tickers.
    3. If total evaluated analogs >= MIN_SAMPLE_THRESHOLD, returns empirical
       distribution with is_empirical=True.
    4. Otherwise, returns a model-estimated distribution that varies by ticker,
       confidence, predicted_gap, and direction, marked is_empirical=False.
    """
    counts = {b: 0 for b in GAP_BUCKETS}
    total_matching = 0

    # Normalize direction to "BTST" or "STBT" for querying
    direction = None
    if signal_direction:
        if "BTST" in signal_direction.upper() or "BUY" in signal_direction.upper():
            direction = "BTST"
        elif "STBT" in signal_direction.upper() or "SELL" in signal_direction.upper() or "PUT" in signal_direction.upper():
            direction = "STBT"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            score_min = max(40, confidence_score - 10)
            score_max = min(100, confidence_score + 10)

            # Step 1: Try ticker-specific + direction + confidence band
            if symbol and direction:
                cursor.execute("""
                    SELECT e.actual_gap_pct FROM signal_evaluations e
                    INNER JOIN signal_journal j ON e.signal_id = j.id
                    WHERE j.symbol = ?
                      AND j.signal LIKE ?
                      AND j.confidence_score BETWEEN ? AND ?
                """, (symbol, f"%{direction}%", score_min, score_max))
                rows = cursor.fetchall()
                for r in rows:
                    actual = float(r[0] if isinstance(r, (tuple, list)) else r["actual_gap_pct"])
                    b = classify_gap_into_bucket(actual)
                    counts[b] += 1
                    total_matching += 1

            # Step 2: If not enough ticker-specific data, broaden to all tickers
            #         with same direction + confidence band
            if total_matching < MIN_SAMPLE_THRESHOLD and direction:
                counts = {b: 0 for b in GAP_BUCKETS}
                total_matching = 0
                cursor.execute("""
                    SELECT e.actual_gap_pct FROM signal_evaluations e
                    INNER JOIN signal_journal j ON e.signal_id = j.id
                    WHERE j.signal LIKE ?
                      AND j.confidence_score BETWEEN ? AND ?
                """, (f"%{direction}%", score_min, score_max))
                rows = cursor.fetchall()
                for r in rows:
                    actual = float(r[0] if isinstance(r, (tuple, list)) else r["actual_gap_pct"])
                    b = classify_gap_into_bucket(actual)
                    counts[b] += 1
                    total_matching += 1

            # Step 3: If still not enough, try any direction + confidence band
            if total_matching < MIN_SAMPLE_THRESHOLD:
                counts = {b: 0 for b in GAP_BUCKETS}
                total_matching = 0
                cursor.execute("""
                    SELECT e.actual_gap_pct FROM signal_evaluations e
                    INNER JOIN signal_journal j ON e.signal_id = j.id
                    WHERE j.confidence_score BETWEEN ? AND ?
                """, (score_min, score_max))
                rows = cursor.fetchall()
                for r in rows:
                    actual = float(r[0] if isinstance(r, (tuple, list)) else r["actual_gap_pct"])
                    b = classify_gap_into_bucket(actual)
                    counts[b] += 1
                    total_matching += 1

    except Exception as e:
        logger.warning(f"Error reading historical gap analogs: {e}")

    # --- Build probability distribution ---
    probs: Dict[str, float] = {}
    is_empirical = total_matching >= MIN_SAMPLE_THRESHOLD

    if is_empirical:
        # Real empirical distribution from evaluated historical data
        for b in GAP_BUCKETS:
            probs[b] = round(counts[b] / total_matching, 3)
    else:
        # Model-estimated distribution — varies by ticker, confidence,
        # predicted gap, and direction
        probs = _build_model_estimate(
            confidence_score, predicted_gap_pct,
            symbol or "UNKNOWN", direction or "BTST"
        )

    most_likely = max(probs, key=probs.get) if probs else "0-1%"
    return {
        "bucket_probabilities": probs,
        "most_likely_bucket": most_likely,
        "sample_size": total_matching,
        "is_empirical": is_empirical,
        "is_sufficient": is_empirical,
        "is_model_estimate": not is_empirical,
    }


# --- Model-estimated distribution builder -------------------------------------
def _build_model_estimate(
    confidence: int,
    predicted_gap: float,
    symbol: str,
    direction: str,
) -> Dict[str, float]:
    """
    Produce a model-estimated 4-bucket distribution that genuinely varies by:
    - predicted_gap_pct magnitude (shifts distribution center)
    - confidence_score (higher -> tighter concentration; lower -> flatter)
    - direction (BTST vs STBT have different typical gap profiles)
    - symbol (per-ticker hash jitter so no two tickers are byte-identical)

    This is *not* empirical data — it's a principled estimate. The frontend
    must label it as "Preliminary" so users know it's not backed by N>=20
    historical analogs.
    """
    est = abs(predicted_gap) if predicted_gap != 0.0 else 0.8

    # Base center: which bucket should have the most mass?
    # Map est to a continuous "center" on [0, 4) where 0=bucket "0-1%", 3=bucket "3%+"
    if est < 1.0:
        center = 0.0 + est * 0.8       # 0.0 - 0.8: mostly in 0-1%
    elif est < 2.0:
        center = 0.8 + (est - 1.0) * 1.2  # 0.8 - 2.0: shifting to 1-2%
    elif est < 3.0:
        center = 2.0 + (est - 2.0) * 0.8  # 2.0 - 2.8: shifting to 2-3%
    else:
        center = min(2.8 + (est - 3.0) * 0.3, 3.5)  # 2.8 - 3.5: mostly 3%+

    # Confidence modulates spread: higher confidence -> tighter distribution
    # Spread = standard deviation in bucket-index units
    # confidence 95 -> spread ~0.6 (tight), confidence 60 -> spread ~1.4 (wide)
    spread = max(0.5, 2.0 - (confidence / 70.0))

    # Direction shift: STBT setups historically show slightly wider spreads
    # (sell-side gaps tend to be more volatile in Indian markets)
    if direction == "STBT":
        spread *= 1.15
        center = min(center + 0.15, 3.5)

    # Per-ticker jitter: add small deterministic perturbation so identical
    # confidence+gap for different tickers don't produce identical output
    jitter_center = (_ticker_hash_float(symbol, "center") - 0.5) * 0.3
    jitter_spread = (_ticker_hash_float(symbol, "spread") - 0.5) * 0.15
    center = max(0.0, min(center + jitter_center, 3.5))
    spread = max(0.4, spread + jitter_spread)

    # Build Gaussian-weighted probabilities for each bucket
    raw = {}
    for i, b in enumerate(GAP_BUCKETS):
        bucket_center = float(i) + 0.5  # center of bucket i in index space
        dist = abs(bucket_center - center)
        weight = math.exp(-0.5 * (dist / spread) ** 2)
        raw[b] = max(weight, 0.02)  # floor at 2% so no bucket is ever exactly 0

    # Normalize to sum to 1.0
    total = sum(raw.values())
    probs = {b: round(raw[b] / total, 3) for b in GAP_BUCKETS}

    # Fix any floating-point rounding so they sum to exactly 1.000
    remainder = round(1.0 - sum(probs.values()), 3)
    if remainder != 0.0:
        probs[max(probs, key=probs.get)] = round(
            probs[max(probs, key=probs.get)] + remainder, 3
        )

    return probs
