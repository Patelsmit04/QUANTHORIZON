"""
Trade Evaluation Engine (evaluation_engine.py)
==============================================
Standardized outcome evaluation, directional classification, and permanent sanity guards
for BTST (BUY) and STBT (SELL) recommendations.

Strict Outcome Classifications:
------------------------------
BTST (BUY / CALL / CE):
  - gap_pct >= +1.5%               -> JACKPOT WIN
  - +0.5% <= gap_pct < +1.5%        -> WIN
  - -0.3% <= gap_pct < +0.5%        -> NEUTRAL
  - gap_pct < -0.3%                -> LOSS

STBT (SELL / PUT / PE):
  - gap_pct <= -1.5%               -> JACKPOT WIN
  - -1.5% < gap_pct <= -0.5%       -> WIN
  - -0.5% < gap_pct <= +0.3%       -> NEUTRAL
  - gap_pct > +0.3%                -> LOSS

Permanent Sanity Assertions:
----------------------------
1. Implausible Gap Guard: Overnight gap > 25.0% on Indian F&O equities indicates feed corruption
   or an unadjusted corporate action (split/bonus). Never auto-grade as WIN or JACKPOT WIN;
   flags as DATA_ANOMALY for manual review.
2. Direction Mismatch Guard: A BUY signal with non-winning gap (gap < 0.5%) or a SELL signal
   with non-winning gap (gap > -0.5%) can NEVER be recorded as WIN or JACKPOT WIN under any
   circumstance. Any breach triggers a CRITICAL log and forces outcome to LOSS.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("EvaluationEngine")

BTST_JACKPOT_THRESHOLD = 1.5
BTST_WIN_THRESHOLD = 0.5
BTST_NEUTRAL_FLOOR = -0.3

STBT_JACKPOT_THRESHOLD = -1.5
STBT_WIN_THRESHOLD = -0.5
STBT_NEUTRAL_CEILING = 0.3

MAX_PLAUSIBLE_OVERNIGHT_GAP = 25.0


def is_buy_signal(signal: str) -> bool:
    """Returns True if signal is bullish / BUY / BTST / CALL / CE."""
    sig = str(signal).upper()
    return any(k in sig for k in ["BTST", "BUY", "CALL", "CE", "BULLISH"])


def is_sell_signal(signal: str) -> bool:
    """Returns True if signal is bearish / SELL / STBT / PUT / PE."""
    sig = str(signal).upper()
    return any(k in sig for k in ["STBT", "SELL", "PUT", "PE", "BEARISH"])


def evaluate_trade_outcome(
    signal: str,
    close_price_325: float,
    open_price_915: float,
    predicted_gap_pct: float = 0.0,
    symbol: str = "",
) -> Dict[str, Any]:
    """
    Evaluates an overnight trade against its opening print with strict direction routing
    and permanent sanity assertions.

    Returns dict with:
      - gap_pct: float
      - variance_error_pct: float
      - accuracy_score_pct: float
      - outcome: 'JACKPOT WIN' | 'WIN' | 'NEUTRAL' | 'LOSS' | 'DATA_ANOMALY'
      - is_anomaly: bool
      - review_required: bool
      - reason: str
    """
    try:
        close_p = float(close_price_325)
        open_p = float(open_price_915)
    except (TypeError, ValueError):
        return {
            "gap_pct": 0.0,
            "variance_error_pct": 0.0,
            "accuracy_score_pct": 0.0,
            "outcome": "DATA_ANOMALY",
            "is_anomaly": True,
            "review_required": True,
            "reason": f"Non-numeric price inputs (close={close_price_325}, open={open_price_915})",
        }

    if close_p <= 0 or open_p <= 0:
        return {
            "gap_pct": 0.0,
            "variance_error_pct": 0.0,
            "accuracy_score_pct": 0.0,
            "outcome": "DATA_ANOMALY",
            "is_anomaly": True,
            "review_required": True,
            "reason": f"Non-positive price (close={close_p}, open={open_p})",
        }

    gap_pct = round(((open_p - close_p) / close_p) * 100, 2)
    pred_gap = float(predicted_gap_pct or 0.0)
    variance_error = round(abs(gap_pct - pred_gap), 2)
    accuracy_score = max(0.0, round(100.0 - (variance_error * 15.0), 1))

    # Plausibility Guard: An overnight gap > 25% on an F&O large-cap stock without corporate
    # action adjustments indicates data corruption.
    if abs(gap_pct) > MAX_PLAUSIBLE_OVERNIGHT_GAP:
        logger.critical(
            f"[EVALUATION DATA ANOMALY] Suspicious overnight gap of {gap_pct}% for {symbol} "
            f"(close={close_p}, open={open_p}). Flagging for MANUAL REVIEW — NEVER auto-grading as WIN."
        )
        return {
            "gap_pct": gap_pct,
            "variance_error_pct": variance_error,
            "accuracy_score_pct": 0.0,
            "outcome": "DATA_ANOMALY",
            "is_anomaly": True,
            "review_required": True,
            "reason": f"Extreme gap of {gap_pct}% exceeds {MAX_PLAUSIBLE_OVERNIGHT_GAP}% sanity bound",
        }

    is_buy = is_buy_signal(signal)
    is_sell = is_sell_signal(signal)

    if not is_buy and not is_sell:
        logger.warning(f"[EVALUATION] Unrecognized signal direction '{signal}' for {symbol} — defaulting to BUY/BTST branch.")
        is_buy = True

    if is_buy:
        if gap_pct >= BTST_JACKPOT_THRESHOLD:
            outcome = "JACKPOT WIN"
        elif gap_pct >= BTST_WIN_THRESHOLD:
            outcome = "WIN"
        elif BTST_NEUTRAL_FLOOR <= gap_pct < BTST_WIN_THRESHOLD:
            outcome = "NEUTRAL"
        else:
            outcome = "LOSS"
    else:  # is_sell
        if gap_pct <= STBT_JACKPOT_THRESHOLD:
            outcome = "JACKPOT WIN"
        elif gap_pct <= STBT_WIN_THRESHOLD:
            outcome = "WIN"
        elif STBT_WIN_THRESHOLD < gap_pct <= STBT_NEUTRAL_CEILING:
            outcome = "NEUTRAL"
        else:
            outcome = "LOSS"

    # PERMANENT SANITY ASSERTION (Circuit Breaker)
    # A WIN or JACKPOT WIN must strictly align with the trade's signal direction and win threshold
    outcome = enforce_direction_sanity(signal, gap_pct, outcome, symbol)

    return {
        "gap_pct": gap_pct,
        "variance_error_pct": variance_error,
        "accuracy_score_pct": accuracy_score,
        "outcome": outcome,
        "is_anomaly": False,
        "review_required": False,
        "reason": "OK",
    }


def enforce_direction_sanity(signal: str, gap_pct: float, outcome: str, symbol: str = "") -> str:
    """
    Hard sanity circuit breaker: Guarantees that no WIN / JACKPOT WIN can ever be recorded
    when the gap does not satisfy the required threshold in the signal direction.
    """
    if "WIN" not in outcome:
        return outcome

    is_buy = is_buy_signal(signal)
    is_sell = is_sell_signal(signal)

    if is_buy and gap_pct < BTST_WIN_THRESHOLD:
        logger.critical(
            f"[SANITY BREACH PREVENTED] {symbol}: BUY signal graded as {outcome} but gap is {gap_pct}% "
            f"(required >= {BTST_WIN_THRESHOLD}%). FORCING outcome to LOSS."
        )
        return "LOSS"

    if is_sell and gap_pct > STBT_WIN_THRESHOLD:
        logger.critical(
            f"[SANITY BREACH PREVENTED] {symbol}: SELL signal graded as {outcome} but gap is {gap_pct}% "
            f"(required <= {STBT_WIN_THRESHOLD}%). FORCING outcome to LOSS."
        )
        return "LOSS"

    return outcome
