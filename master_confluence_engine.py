"""
TRADEXO Master Confluence Engine (MCE v1)
Version: 47.0.0
Institutional Ensemble Layer for BTST/STBT Decision Synthesis.

Features:
1. Strict Anti-Double-Counting factor groups with hard caps summing to 100%.
2. Directional Intra-group Scoring (Bullish vs Bearish) with diminishing marginal weights (1.0, 0.5, 0.0).
3. Confluence Magnitude and Conflict Filter (High Magnitude + Low Directional Separation => NO TRADE).
4. Immutable Data Lineage & Frozen Model Governance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FactorSignal:
    name: str
    direction: str  # "BULLISH", "BEARISH", "NEUTRAL"
    score: float  # Raw factor strength in [0.0, 100.0]
    source: str  # e.g., "VWAP_STRATEGY", "PILLAR_1_OI", "SMC_OB"
    timestamp: str = ""


@dataclass
class FactorGroupConfig:
    group_id: str
    name: str
    weight: float
    cap: float
    description: str


# 6 Factor Groups with Caps strictly summing to 100.0
FACTOR_GROUPS: Dict[str, FactorGroupConfig] = {
    "G1": FactorGroupConfig(
        group_id="G1",
        name="Price / Technical Trend",
        weight=0.25,
        cap=25.0,
        description="VWAP Pullback, Death/Golden Cross, EMA slope, RSI(14)",
    ),
    "G2": FactorGroupConfig(
        group_id="G2",
        name="Volume & Open Interest",
        weight=0.20,
        cap=20.0,
        description="Futures OI Build, Volume Persistence, Surge, Strategy OI",
    ),
    "G3": FactorGroupConfig(
        group_id="G3",
        name="Market Structure & SMC",
        weight=0.20,
        cap=20.0,
        description="Marubozu Close, SMC Order Blocks, Fair Value Gaps, ORB 30",
    ),
    "G4": FactorGroupConfig(
        group_id="G4",
        name="Institutional Order Flow",
        weight=0.15,
        cap=15.0,
        description="Bulk/Block Deals, Synthetic CVD accumulation, L2 Depth",
    ),
    "G5": FactorGroupConfig(
        group_id="G5",
        name="Macro & Market Regime",
        weight=0.10,
        cap=10.0,
        description="Relative Strength vs Nifty/Sector, GIFT NIFTY, India VIX",
    ),
    "G6": FactorGroupConfig(
        group_id="G6",
        name="Execution & Data Quality",
        weight=0.10,
        cap=10.0,
        description="Spread penalty, L2 liquidity depth, feed freshness",
    ),
}

# Marginal weights for diminishing intra-group confirmation
MARGINAL_WEIGHTS = [1.00, 0.50]  # 3rd and subsequent factors receive 0.00


@dataclass
class GroupScoreDetail:
    group_id: str
    name: str
    weight: float
    cap: float
    raw_bullish: float
    raw_bearish: float
    bullish_contribution: float
    bearish_contribution: float
    bullish_factors: List[str]
    bearish_factors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "name": self.name,
            "weight": self.weight,
            "cap": self.cap,
            "raw_bullish": round(self.raw_bullish, 2),
            "raw_bearish": round(self.raw_bearish, 2),
            "bullish_contribution": round(self.bullish_contribution, 2),
            "bearish_contribution": round(self.bearish_contribution, 2),
            "bullish_factors": self.bullish_factors,
            "bearish_factors": self.bearish_factors,
        }


@dataclass
class MasterConfluenceResult:
    symbol: str
    decision: str  # "STRONG BTST", "BTST", "NO TRADE", "STBT", "STRONG STBT"
    directional_score: float  # [-100.0, +100.0]
    bullish_score: float  # [0.0, 100.0]
    bearish_score: float  # [0.0, 100.0]
    confluence_magnitude: float  # [0.0, 200.0]
    has_conflict: bool
    conflict_reason: Optional[str]
    group_breakdown: Dict[str, GroupScoreDetail]
    invalidation_conditions: List[str]
    # Model Governance & Lineage Metadata
    model_id: str = "TRADEXO-MCE-V1"
    model_version: str = "2026.09.v1"
    training_data_cutoff: str = "2026-08-31"
    validation_period: str = "2026-06-01 to 2026-08-31"
    deployment_timestamp: str = ""
    approval_status: str = "FROZEN_PRODUCTION"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "decision": self.decision,
            "directional_score": round(self.directional_score, 2),
            "bullish_score": round(self.bullish_score, 2),
            "bearish_score": round(self.bearish_score, 2),
            "confluence_magnitude": round(self.confluence_magnitude, 2),
            "has_conflict": self.has_conflict,
            "conflict_reason": self.conflict_reason,
            "group_breakdown": {k: v.to_dict() for k, v in self.group_breakdown.items()},
            "invalidation_conditions": self.invalidation_conditions,
            "lineage": {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "training_data_cutoff": self.training_data_cutoff,
                "validation_period": self.validation_period,
                "deployment_timestamp": self.deployment_timestamp,
                "approval_status": self.approval_status,
            },
        }


def _calculate_intra_group_score(factors: List[FactorSignal]) -> Tuple[float, List[str]]:
    """
    Computes intra-group score in [0, 100] using diminishing marginal returns:
    alpha_1 = 1.00, alpha_2 = 0.50, alpha_>=3 = 0.00
    """
    if not factors:
        return 0.0, []

    # Sort descending by standalone score
    sorted_factors = sorted(factors, key=lambda f: f.score, reverse=True)
    names = [f"{f.name} ({f.score:.0f})" for f in sorted_factors]

    weighted_sum = 0.0
    weight_total = 0.0

    for i, factor in enumerate(sorted_factors):
        alpha = MARGINAL_WEIGHTS[i] if i < len(MARGINAL_WEIGHTS) else 0.00
        if alpha <= 0.0:
            break
        clamped_score = max(0.0, min(100.0, float(factor.score)))
        weighted_sum += alpha * clamped_score
        weight_total += alpha

    if weight_total <= 0.0:
        return 0.0, names

    raw_score = min(100.0, weighted_sum / weight_total)
    return raw_score, names


class MasterConfluenceEngine:
    """
    Synthesizes multiple legacy strategies and 6-pillar indicators into an institutional
    directionally unambiguous confluence decision.
    """

    def __init__(self):
        self.model_id = "TRADEXO-MCE-V1"
        self.model_version = "2026.09.v1"
        self.training_data_cutoff = "2026-08-31"
        self.validation_period = "2026-06-01 to 2026-08-31"
        self.approval_status = "FROZEN_PRODUCTION"

    def evaluate_confluence(
        self,
        symbol: str,
        factor_signals: Dict[str, List[FactorSignal]],
        data_quality_tradable: bool = True,
        quarantined_strategy_ids: Optional[List[str]] = None,
    ) -> MasterConfluenceResult:
        """
        Executes formal MCE v1 evaluation for a given symbol.
        `factor_signals` maps group_id ("G1"..."G6") to list of FactorSignal instances.
        Quarantined strategies are filtered out of voting.
        """
        quarantined_set = set(quarantined_strategy_ids or [])
        now_iso = datetime.now(timezone.utc).isoformat()
        group_details: Dict[str, GroupScoreDetail] = {}

        total_bullish_score = 0.0
        total_bearish_score = 0.0
        invalidation_conditions = []

        # 1. Process each of the 6 factor groups
        for group_id, cfg in FACTOR_GROUPS.items():
            raw_factors = factor_signals.get(group_id, [])
            # Filter out signals from quarantined strategies
            active_factors = [
                f for f in raw_factors if f.source not in quarantined_set
            ]

            bullish_list = [f for f in active_factors if f.direction.upper() == "BULLISH"]
            bearish_list = [f for f in active_factors if f.direction.upper() == "BEARISH"]

            raw_bullish, bull_names = _calculate_intra_group_score(bullish_list)
            raw_bearish, bear_names = _calculate_intra_group_score(bearish_list)

            # Apply group weight and cap
            bull_contrib = min(raw_bullish * cfg.weight, cfg.cap)
            bear_contrib = min(raw_bearish * cfg.weight, cfg.cap)

            total_bullish_score += bull_contrib
            total_bearish_score += bear_contrib

            group_details[group_id] = GroupScoreDetail(
                group_id=group_id,
                name=cfg.name,
                weight=cfg.weight,
                cap=cfg.cap,
                raw_bullish=raw_bullish,
                raw_bearish=raw_bearish,
                bullish_contribution=bull_contrib,
                bearish_contribution=bear_contrib,
                bullish_factors=bull_names,
                bearish_factors=bear_names,
            )

        # 2. Compute Directional Score and Confluence Magnitude
        directional_score = total_bullish_score - total_bearish_score
        confluence_magnitude = total_bullish_score + total_bearish_score

        # 3. Conflict Filter: High magnitude + Low directional separation
        has_conflict = False
        conflict_reason = None
        if confluence_magnitude >= 60.0 and abs(directional_score) < 30.0:
            has_conflict = True
            conflict_reason = (
                f"Directional Conflict: High Confluence Magnitude ({confluence_magnitude:.1f}) "
                f"with Low Directional Separation ({directional_score:.1f}). Evidence is divided."
            )

        # 4. Fail-closed Data Quality override
        if not data_quality_tradable:
            decision = "NO TRADE"
            invalidation_conditions.append("Data quality gate failed or quote is stale/missing.")
        elif has_conflict:
            decision = "NO TRADE"
            invalidation_conditions.append(conflict_reason)
        else:
            # 5. Apply Formal Decision Thresholds
            if directional_score >= 70.0:
                decision = "STRONG BTST"
                invalidation_conditions.append("Invalidate if 15m VWAP broken or GIFT Nifty drops > 0.5%.")
            elif directional_score >= 30.0:
                decision = "BTST"
                invalidation_conditions.append("Invalidate if 5m close breaches previous candle low.")
            elif directional_score <= -70.0:
                decision = "STRONG STBT"
                invalidation_conditions.append("Invalidate if 15m VWAP reclaimed or GIFT Nifty rallies > 0.5%.")
            elif directional_score <= -30.0:
                decision = "STBT"
                invalidation_conditions.append("Invalidate if 5m close breaches previous candle high.")
            else:
                decision = "NO TRADE"
                invalidation_conditions.append("Directional conviction below +-30.0 minimum threshold.")

        return MasterConfluenceResult(
            symbol=symbol,
            decision=decision,
            directional_score=directional_score,
            bullish_score=total_bullish_score,
            bearish_score=total_bearish_score,
            confluence_magnitude=confluence_magnitude,
            has_conflict=has_conflict,
            conflict_reason=conflict_reason,
            group_breakdown=group_details,
            invalidation_conditions=invalidation_conditions,
            model_id=self.model_id,
            model_version=self.model_version,
            training_data_cutoff=self.training_data_cutoff,
            validation_period=self.validation_period,
            deployment_timestamp=now_iso,
            approval_status=self.approval_status,
        )


# Global singleton instance
master_confluence_engine = MasterConfluenceEngine()
