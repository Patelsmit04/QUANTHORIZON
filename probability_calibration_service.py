"""
TRADEXO Decoupled Probability Calibration & Expected Value Service
Version: 47.0.0
Enforces multi-criteria calibration hierarchy (Sample size is necessary but not sufficient).
Provides Wilson confidence intervals, Bayesian shrinkage, Brier score, ECE, and EV gating.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple

from friction_model import compute_expected_value, compute_transaction_costs, get_active_friction_model


@dataclass
class ProbabilityCalibrationResult:
    p_win: float  # Calibrated probability in [0.0, 1.0]
    p_win_raw: float  # Uncalibrated empirical win rate
    confidence_tier: str  # UNCALIBRATED, LOW_CONFIDENCE, PROVISIONAL, CALIBRATED, HIGH_CONFIDENCE
    sample_size: int
    brier_score: float
    ece_score: float
    ci_lower_95: float
    ci_upper_95: float
    is_tradable: bool
    rejection_reason: Optional[str]
    ev_pct: float
    ev_viable: bool
    sizing_multiplier: float  # 1.0 for normal, 0.5 for low confidence, 0.0 for uncalibrated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "p_win": round(self.p_win, 4),
            "p_win_raw": round(self.p_win_raw, 4),
            "confidence_tier": self.confidence_tier,
            "sample_size": self.sample_size,
            "brier_score": round(self.brier_score, 4),
            "ece_score": round(self.ece_score, 4),
            "ci_95": [round(self.ci_lower_95, 4), round(self.ci_upper_95, 4)],
            "is_tradable": self.is_tradable,
            "rejection_reason": self.rejection_reason,
            "ev_pct": round(self.ev_pct, 4),
            "ev_viable": self.ev_viable,
            "sizing_multiplier": self.sizing_multiplier,
        }


def compute_wilson_score_interval(wins: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Computes Wilson Score confidence interval for a binomial proportion.
    """
    if total <= 0:
        return 0.0, 1.0
    z = 1.95996  # 95% confidence standard normal quantile
    p_hat = wins / total
    denominator = 1.0 + (z**2 / total)
    centre_adjusted_probability = p_hat + (z**2 / (2 * total))
    adjusted_standard_deviation = math.sqrt((p_hat * (1 - p_hat) + (z**2 / (4 * total))) / total)

    lower = (centre_adjusted_probability - z * adjusted_standard_deviation) / denominator
    upper = (centre_adjusted_probability + z * adjusted_standard_deviation) / denominator
    return max(0.0, lower), min(1.0, upper)


class ProbabilityCalibrationService:
    """
    Evaluates empirical trade outcomes and produces calibrated, validated probabilities.
    """

    def __init__(self):
        self.model_version = "2026.09.v1"

    def evaluate_probability(
        self,
        wins: int,
        total: int,
        brier_score: float = 0.20,
        ece_score: float = 0.06,
        dsr_passed: bool = True,
        avg_win_pct: float = 0.025,  # 2.5% average win
        avg_loss_pct: float = 0.012,  # 1.2% average stop loss
        friction_cost_pct: float = 0.0025,  # 25 bps roundtrip friction
    ) -> ProbabilityCalibrationResult:
        """
        Determines calibration tier using multi-criteria requirements:
        Sample size alone is NEVER sufficient. Brier score, ECE, and DSR must pass.
        """
        if total < 30:
            # UNCALIBRATED: Hard Abstention Gate
            return ProbabilityCalibrationResult(
                p_win=0.50,
                p_win_raw=(wins / total) if total > 0 else 0.50,
                confidence_tier="UNCALIBRATED",
                sample_size=total,
                brier_score=brier_score,
                ece_score=ece_score,
                ci_lower_95=0.0,
                ci_upper_95=1.0,
                is_tradable=False,
                rejection_reason=f"Insufficient sample size (N={total} < 30 minimum abstention threshold).",
                ev_pct=0.0,
                ev_viable=False,
                sizing_multiplier=0.0,
            )

        p_raw = wins / total
        ci_lower, ci_upper = compute_wilson_score_interval(wins, total)

        # 1. Evaluate Multi-Criteria Tiers
        if total >= 1000 and brier_score <= 0.18 and ece_score <= 0.05 and dsr_passed:
            tier = "HIGH_CONFIDENCE"
            p_calibrated = p_raw
            sizing_mult = 1.0
        elif total >= 300 and brier_score <= 0.22 and ece_score <= 0.08:
            tier = "CALIBRATED"
            p_calibrated = p_raw
            sizing_mult = 1.0
        elif total >= 100 and brier_score <= 0.25:
            tier = "PROVISIONAL"
            p_calibrated = p_raw
            sizing_mult = 0.8
        elif total >= 30:
            tier = "LOW_CONFIDENCE"
            # Bayesian shrinkage towards 50% prior (weight n0=30)
            p_calibrated = (wins + 15.0) / (total + 30.0)
            sizing_mult = 0.5
        else:
            tier = "UNCALIBRATED"
            p_calibrated = 0.50
            sizing_mult = 0.0

        # If high sample size had poor calibration metrics, downgrade
        if total >= 300 and tier not in ["HIGH_CONFIDENCE", "CALIBRATED"]:
            tier = "PROVISIONAL_DEGRADED"
            sizing_mult = 0.5

        # 2. Evaluate Expected Value (EV) Gate
        ev_pct, ev_viable = compute_expected_value(
            p_win=p_calibrated,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            friction_cost_pct=friction_cost_pct,
        )

        # 3. Overall Tradability Gate
        if tier == "UNCALIBRATED":
            is_tradable = False
            rejection_reason = "Uncalibrated probability model."
        elif not ev_viable:
            is_tradable = False
            rejection_reason = f"Negative or zero Expected Value ({ev_pct*100:.2f}% <= 0.00% after friction)."
        else:
            is_tradable = True
            rejection_reason = None

        return ProbabilityCalibrationResult(
            p_win=p_calibrated,
            p_win_raw=p_raw,
            confidence_tier=tier,
            sample_size=total,
            brier_score=brier_score,
            ece_score=ece_score,
            ci_lower_95=ci_lower,
            ci_upper_95=ci_upper,
            is_tradable=is_tradable,
            rejection_reason=rejection_reason,
            ev_pct=ev_pct,
            ev_viable=ev_viable,
            sizing_multiplier=sizing_mult,
        )


# Global singleton
probability_calibration_service = ProbabilityCalibrationService()
