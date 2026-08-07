"""
PROBABILITY-BUCKETED GAP FORECAST ENGINE
========================================
Calculates empirical probability distribution across 7 overnight gap buckets:
0-0.3%, 0.3-0.5%, 0.5-1.0%, 1.0-1.7%, 1.7-2.0%, 2.0-3.0%, 3.0%+

Uses historical analog matching over evaluated signals in signal_journal.py
to ground bucket probabilities in real past performance data.
"""

import math
import logging
from typing import Dict, List, Any, Optional
from signal_journal import get_db_connection

logger = logging.getLogger("GapBucketEngine")

GAP_BUCKETS = [
    "0-0.3%",
    "0.3-0.5%",
    "0.5-1.0%",
    "1.0-1.7%",
    "1.7-2.0%",
    "2.0-3.0%",
    "3.0%+"
]


def classify_gap_into_bucket(actual_gap_pct: float) -> str:
    """Classify a realized gap percentage into one of the 7 discrete buckets."""
    abs_gap = abs(actual_gap_pct)
    if abs_gap < 0.3:
        return "0-0.3%"
    elif abs_gap < 0.5:
        return "0.3-0.5%"
    elif abs_gap < 1.0:
        return "0.5-1.0%"
    elif abs_gap < 1.7:
        return "1.0-1.7%"
    elif abs_gap < 2.0:
        return "1.7-2.0%"
    elif abs_gap < 3.0:
        return "2.0-3.0%"
    else:
        return "3.0%+"


def calculate_gap_bucket_distribution(
    confidence_score: int,
    predicted_gap_pct: float,
    symbol: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compute empirical probability distribution for overnight gap landing in each bucket.
    Pulls past evaluated setups from signal_journal with matching confidence bands.
    """
    counts = {b: 0 for b in GAP_BUCKETS}
    total_matching = 0

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            score_min = max(40, confidence_score - 10)
            score_max = min(100, confidence_score + 10)
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

    probs: Dict[str, float] = {}
    if total_matching >= 10:
        for b in GAP_BUCKETS:
            probs[b] = round(counts[b] / total_matching, 3)
    else:
        # Seed distribution dynamically around predicted_gap_pct using calibrated curve
        est = abs(predicted_gap_pct) if predicted_gap_pct != 0.0 else 0.8
        raw = {}
        if est < 0.4:
            raw = {"0-0.3%": 0.45, "0.3-0.5%": 0.30, "0.5-1.0%": 0.15, "1.0-1.7%": 0.06, "1.7-2.0%": 0.02, "2.0-3.0%": 0.01, "3.0%+": 0.01}
        elif est < 0.9:
            raw = {"0-0.3%": 0.15, "0.3-0.5%": 0.25, "0.5-1.0%": 0.38, "1.0-1.7%": 0.14, "1.7-2.0%": 0.05, "2.0-3.0%": 0.02, "3.0%+": 0.01}
        elif est < 1.6:
            raw = {"0-0.3%": 0.08, "0.3-0.5%": 0.14, "0.5-1.0%": 0.28, "1.0-1.7%": 0.34, "1.7-2.0%": 0.10, "2.0-3.0%": 0.04, "3.0%+": 0.02}
        elif est < 2.5:
            raw = {"0-0.3%": 0.05, "0.3-0.5%": 0.08, "0.5-1.0%": 0.17, "1.0-1.7%": 0.28, "1.7-2.0%": 0.22, "2.0-3.0%": 0.14, "3.0%+": 0.06}
        else:
            raw = {"0-0.3%": 0.03, "0.3-0.5%": 0.05, "0.5-1.0%": 0.12, "1.0-1.7%": 0.20, "1.7-2.0%": 0.25, "2.0-3.0%": 0.23, "3.0%+": 0.12}

        s = sum(raw.values())
        probs = {b: round(raw[b] / s, 3) for b in GAP_BUCKETS}

    most_likely = max(probs, key=probs.get)
    return {
        "bucket_probabilities": probs,
        "most_likely_bucket": most_likely,
        "sample_size": total_matching,
        "is_empirical": total_matching >= 10
    }
