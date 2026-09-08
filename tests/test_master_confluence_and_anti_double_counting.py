"""
TRADEXO Master Confluence Engine & Anti-Double-Counting Tests
Validates mathematical formalization, group caps, marginal decay,
directional separation, strategy quarantine, and paper accounting integrity.
"""

import pytest

from contract_spec_provider import CONTRACT_REGISTRY, get_contract_spec
from friction_model import (
    compute_expected_value,
    compute_transaction_costs,
    get_active_friction_model,
)
from master_confluence_engine import (
    FACTOR_GROUPS,
    FactorSignal,
    MasterConfluenceEngine,
    _calculate_intra_group_score,
)
from paper_trading_service import (
    close_paper_position,
    execute_paper_order,
    get_paper_portfolio,
    reset_paper_account,
)
from probability_calibration_service import probability_calibration_service
from risk_gate_service import QuarantineStatus, RiskGateService


class TestMasterConfluenceAndAntiDoubleCounting:

    def test_group_caps_strictly_sum_to_100(self):
        """Mathematically verifies that all 6 group caps sum to exactly 100.0 points."""
        total_caps = sum(cfg.cap for cfg in FACTOR_GROUPS.values())
        total_weights = sum(cfg.weight for cfg in FACTOR_GROUPS.values())

        assert round(total_caps, 2) == 100.0, f"Expected caps to sum to 100.0, got {total_caps}"
        assert round(total_weights, 2) == 1.0, f"Expected weights to sum to 1.0, got {total_weights}"

    def test_intra_group_diminishing_marginal_returns(self):
        """
        Verifies intra-group marginal decay:
        alpha_1 = 1.00, alpha_2 = 0.50, alpha_>=3 = 0.00.
        3rd redundant indicator cannot inflate score.
        """
        # Single strong indicator
        f1 = [FactorSignal("VWAP Cross", "BULLISH", 80.0, "s1")]
        score_1, _ = _calculate_intra_group_score(f1)
        assert round(score_1, 2) == 80.0

        # Two indicators: 1st=80, 2nd=50
        # Weighted = (1.0*80 + 0.5*50) / 1.5 = (80 + 25) / 1.5 = 105 / 1.5 = 70.0
        f2 = [
            FactorSignal("VWAP Cross", "BULLISH", 80.0, "s1"),
            FactorSignal("EMA Slope", "BULLISH", 50.0, "s2"),
        ]
        score_2, _ = _calculate_intra_group_score(f2)
        assert round(score_2, 2) == 70.0

        # Add 3rd indicator of 90 (sorted: 90, 80, 50)
        # alpha_1=1.0 for 90, alpha_2=0.5 for 80, alpha_3=0.0 for 50
        # Weighted = (1.0*90 + 0.5*80) / 1.5 = (90 + 40) / 1.5 = 130 / 1.5 = 86.67
        f3 = [
            FactorSignal("VWAP Cross", "BULLISH", 80.0, "s1"),
            FactorSignal("EMA Slope", "BULLISH", 50.0, "s2"),
            FactorSignal("RSI Momentum", "BULLISH", 90.0, "s3"),
        ]
        score_3, _ = _calculate_intra_group_score(f3)
        assert round(score_3, 2) == 86.67

        # Add 4th indicator of 100 (sorted: 100, 90, 80, 50)
        # Weighted = (1.0*100 + 0.5*90) / 1.5 = (100 + 45) / 1.5 = 145 / 1.5 = 96.67
        # The 80 and 50 are ignored by alpha_>=3 = 0.00
        f4 = f3 + [FactorSignal("Golden Cross", "BULLISH", 100.0, "s4")]
        score_4, _ = _calculate_intra_group_score(f4)
        assert round(score_4, 2) == 96.67

    def test_group_contribution_capped(self):
        """Verifies that even if raw score is 100, contribution cannot exceed group cap."""
        mce = MasterConfluenceEngine()
        # Group 1 has weight 0.25 and cap 25.0
        factors = {
            "G1": [
                FactorSignal("VWAP 1", "BULLISH", 100.0, "s1"),
                FactorSignal("VWAP 2", "BULLISH", 100.0, "s2"),
            ]
        }
        res = mce.evaluate_confluence("RELIANCE", factors)
        g1_detail = res.group_breakdown["G1"]
        assert g1_detail.raw_bullish == 100.0
        assert g1_detail.bullish_contribution == 25.0  # Capped at exactly 25.0
        assert res.bullish_score == 25.0

    def test_directional_decision_thresholds(self):
        """Verifies clear mapping from DirectionalScore to decision outputs."""
        mce = MasterConfluenceEngine()

        # 1. STRONG BTST (DirectionalScore >= 70.0)
        # Give full 100 on G1 (25), G2 (20), G3 (20), G4 (15) => Bullish = 80.0
        bull_factors = {
            "G1": [FactorSignal("f", "BULLISH", 100.0, "s")],
            "G2": [FactorSignal("f", "BULLISH", 100.0, "s")],
            "G3": [FactorSignal("f", "BULLISH", 100.0, "s")],
            "G4": [FactorSignal("f", "BULLISH", 100.0, "s")],
        }
        res_strong_buy = mce.evaluate_confluence("RELIANCE", bull_factors)
        assert res_strong_buy.directional_score == 80.0
        assert res_strong_buy.decision == "STRONG BTST"

        # 2. MODERATE BTST (30.0 <= DirectionalScore < 70.0)
        # G1 (25) + G2 (20) => Bullish = 45.0
        moderate_factors = {
            "G1": [FactorSignal("f", "BULLISH", 100.0, "s")],
            "G2": [FactorSignal("f", "BULLISH", 100.0, "s")],
        }
        res_mod_buy = mce.evaluate_confluence("RELIANCE", moderate_factors)
        assert res_mod_buy.directional_score == 45.0
        assert res_mod_buy.decision == "BTST"

        # 3. NO TRADE (-29.9 <= DirectionalScore <= 29.9)
        # G1 (25) Bullish, G2 (20) Bearish => Directional = +5.0 (Below 30 threshold)
        weak_factors = {
            "G1": [FactorSignal("f", "BULLISH", 100.0, "s")],
            "G2": [FactorSignal("f", "BEARISH", 100.0, "s")],
        }
        res_weak = mce.evaluate_confluence("RELIANCE", weak_factors)
        assert res_weak.directional_score == 5.0
        assert res_weak.decision == "NO TRADE"

        # 4. STRONG STBT (DirectionalScore <= -70.0)
        bear_factors = {
            "G1": [FactorSignal("f", "BEARISH", 100.0, "s")],
            "G2": [FactorSignal("f", "BEARISH", 100.0, "s")],
            "G3": [FactorSignal("f", "BEARISH", 100.0, "s")],
            "G4": [FactorSignal("f", "BEARISH", 100.0, "s")],
        }
        res_strong_sell = mce.evaluate_confluence("RELIANCE", bear_factors)
        assert res_strong_sell.directional_score == -80.0
        assert res_strong_sell.decision == "STRONG STBT"

    def test_quarantined_strategy_excluded_from_voting(self):
        """Verifies that quarantined strategy signals are barred from contributing to MCE score."""
        mce = MasterConfluenceEngine()
        factors = {
            "G1": [
                FactorSignal("VWAP Signal", "BULLISH", 100.0, source="vwap-pullback-v1"),
            ]
        }
        # When active: G1 contribution is 25.0
        active_res = mce.evaluate_confluence("RELIANCE", factors)
        assert active_res.bullish_score == 25.0

        # When quarantined: G1 factor from "vwap-pullback-v1" is ignored
        quarantined_res = mce.evaluate_confluence(
            "RELIANCE", factors, quarantined_strategy_ids=["vwap-pullback-v1"]
        )
        assert quarantined_res.bullish_score == 0.0
        assert quarantined_res.decision == "NO TRADE"

    def test_progressive_strategy_quarantine_stages(self):
        """Verifies 20-warn, 50-evaluation, and 100-quarantine progression."""
        risk = RiskGateService()

        # 1. 10 trades: still building sample
        trades_10 = [{"pnl": -100.0} for _ in range(10)]
        assert risk.evaluate_strategy_health("s1", trades_10) == QuarantineStatus.ACTIVE

        # 2. 25 trades with 30% win rate: triggers DEGRADATION_WARNING (not auto quarantine)
        trades_25 = [{"pnl": 100.0} if i < 7 else {"pnl": -100.0} for i in range(25)]
        assert risk.evaluate_strategy_health("s1", trades_25) == QuarantineStatus.DEGRADATION_WARNING

        # 3. 55 trades with 30% win rate: triggers DEGRADATION_EVALUATION
        trades_55 = [{"pnl": 100.0} if i < 16 else {"pnl": -100.0} for i in range(55)]
        assert risk.evaluate_strategy_health("s1", trades_55) == QuarantineStatus.DEGRADATION_EVALUATION

        # 4. 110 trades with 30% win rate: triggers QUARANTINED_AUTO
        trades_110 = [{"pnl": 100.0} if i < 33 else {"pnl": -100.0} for i in range(110)]
        assert risk.evaluate_strategy_health("s1", trades_110) == QuarantineStatus.QUARANTINED_AUTO
        assert "s1" in risk.get_quarantined_strategy_ids()

    def test_paper_trading_capital_invariant(self):
        """Verifies that paper trading satisfies the Capital Accounting Invariant."""
        reset_res = reset_paper_account(starting_capital=1_000_000.0)
        assert reset_res["ok"]

        # Place a sandbox order
        order_res = execute_paper_order({
            "symbol": "RELIANCE",
            "order_type": "BUY",
            "quantity": 1,
            "entry_price": 2900.0,
            "is_paper_sandbox": True,
        })
        assert order_res["ok"], order_res.get("error")
        pos_id = order_res["position_id"]

        # Check invariant while position is open
        portfolio = get_paper_portfolio()
        assert portfolio["account"]["capital_invariant_verified"]

        # Close position with net profit after all institutional charges
        close_res = close_paper_position(pos_id, exit_price=3050.0)
        assert close_res["ok"]

        # Check invariant after close
        portfolio_closed = get_paper_portfolio()
        assert portfolio_closed["account"]["capital_invariant_verified"]
        assert portfolio_closed["account"]["total_trades"] == 1
        assert portfolio_closed["account"]["winning_trades"] == 1
