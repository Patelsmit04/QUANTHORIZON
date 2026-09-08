"""
TRADEXO Negative Safety Gates Test Suite
Validates that the institutional engine refuses to trade under all unsafe,
degraded, uncalibrated, or risk-violating conditions.
"""

from datetime import datetime, timedelta, timezone
import pytest

from contract_spec_provider import get_contract_spec, validate_contract_order
from data_quality_gate import DataQualityState, evaluate_quote_quality
from master_confluence_engine import FactorSignal, master_confluence_engine
from probability_calibration_service import probability_calibration_service
from risk_gate_service import RiskGateService


class TestNegativeSafetyGates:

    def test_gate_1_refuses_missing_price(self):
        """Must reject order and flag MISSING when price is None or <= 0."""
        audit = evaluate_quote_quality("RELIANCE", price=None)
        assert not audit.is_tradable
        assert audit.state == DataQualityState.MISSING

        audit_zero = evaluate_quote_quality("RELIANCE", price=0.0)
        assert not audit_zero.is_tradable
        assert audit_zero.state == DataQualityState.MISSING

    def test_gate_2_refuses_stale_quotes(self):
        """Must reject order and flag STALE when quote is older than 15 seconds."""
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=25)
        audit = evaluate_quote_quality("RELIANCE", price=2950.0, last_updated=stale_time)
        assert not audit.is_tradable
        assert audit.state == DataQualityState.STALE
        assert audit.age_seconds >= 24.0

    def test_gate_3_refuses_inverted_orderbook(self):
        """Must reject and flag ERROR if bid > ask."""
        audit = evaluate_quote_quality("RELIANCE", price=2950.0, bid=2955.0, ask=2950.0)
        assert not audit.is_tradable
        assert audit.state == DataQualityState.ERROR

    def test_gate_4_refuses_excessive_spread(self):
        """Must reject execution if bid-ask spread exceeds 3.0%."""
        # Bid = 100, Ask = 105 (Spread = 5/105 = 4.76% > 3.0%)
        audit = evaluate_quote_quality("NIFTY 24500 CE", price=102.0, bid=100.0, ask=105.0)
        assert not audit.is_tradable
        assert "exceeds execution limit" in (audit.rejection_reason or "")

    def test_gate_5_refuses_invalid_lot_size(self):
        """Must reject orders where quantity is not a valid multiple of official lot size."""
        # NIFTY lot size is 25
        valid, msg = validate_contract_order("NIFTY", quantity=17, price=24500.0, is_option=True)
        assert not valid
        assert "not a valid multiple of lot size" in msg

        # BANKNIFTY lot size is 15
        valid_bn, msg_bn = validate_contract_order("BANKNIFTY", quantity=20, price=52000.0, is_option=True)
        assert not valid_bn
        assert "not a valid multiple of lot size" in msg_bn

    def test_gate_6_refuses_tick_size_violation(self):
        """Must reject orders with price violating minimum tick size of 0.05."""
        valid, msg = validate_contract_order("RELIANCE", quantity=250, price=2950.123, is_option=True)
        assert not valid
        assert "violates minimum tick size" in msg

    def test_gate_7_refuses_uncalibrated_probability_sample(self):
        """Must abstain (NO TRADE) when sample size N < 30."""
        res = probability_calibration_service.evaluate_probability(wins=18, total=25)
        assert not res.is_tradable
        assert res.confidence_tier == "UNCALIBRATED"
        assert res.sizing_multiplier == 0.0
        assert "minimum abstention threshold" in (res.rejection_reason or "")

    def test_gate_8_refuses_negative_expected_value(self):
        """Must refuse trade when expected value is negative after friction."""
        # Win rate 45%, Avg win 1.0%, Avg loss 1.5%, Friction 0.35%
        # EV = 0.45*1.0 - 0.55*1.5 - 0.35 = 0.45 - 0.825 - 0.35 = -0.725% <= 0
        res = probability_calibration_service.evaluate_probability(
            wins=45, total=100, avg_win_pct=0.010, avg_loss_pct=0.015, friction_cost_pct=0.0035
        )
        assert not res.is_tradable
        assert not res.ev_viable
        assert res.ev_pct < 0.0
        assert "Negative or zero Expected Value" in (res.rejection_reason or "")

    def test_gate_9_refuses_single_position_limit_breach(self):
        """Must refuse order requiring > 25% account equity."""
        risk = RiskGateService(starting_capital=1_000_000.0)
        # Order requiring ₹300,000 margin on ₹10L equity (30% > 25%)
        eval_res = risk.evaluate_order_risk(
            symbol="RELIANCE", order_margin=300_000.0, current_equity=1_000_000.0, open_positions=[]
        )
        assert not eval_res.passed
        assert "exceeds 25% single position limit" in (eval_res.rejection_reason or "")

    def test_gate_10_refuses_sector_concentration_breach(self):
        """Must refuse order pushing sector exposure > 30%."""
        risk = RiskGateService(starting_capital=1_000_000.0)
        # Existing open banking positions: HDFCBANK (₹180,000) + ICICIBANK (₹100,000) = ₹280,000 (28%)
        existing = [
            {"symbol": "HDFCBANK", "margin": 180_000.0},
            {"symbol": "ICICIBANK", "margin": 100_000.0},
        ]
        # Candidate order: SBIN for ₹50,000 (Total banking = ₹330,000 = 33% > 30%)
        eval_res = risk.evaluate_order_risk(
            symbol="SBIN", order_margin=50_000.0, current_equity=1_000_000.0, open_positions=existing
        )
        assert not eval_res.passed
        assert "exceeds 30% sector limit" in (eval_res.rejection_reason or "")

    def test_gate_11_refuses_correlated_cluster_breach(self):
        """Must refuse order pushing correlated cluster (rho >= 0.70) > 25%."""
        risk = RiskGateService(starting_capital=1_000_000.0)
        # Existing position: TCS with ₹180,000 margin (18%)
        existing = [{"symbol": "TCS", "margin": 180_000.0}]
        # Candidate: INFY (TCS-INFY correlation rho >= 0.70) with ₹90,000 margin (Combined = 27% > 25%)
        eval_res = risk.evaluate_order_risk(
            symbol="INFY", order_margin=90_000.0, current_equity=1_000_000.0, open_positions=existing
        )
        assert not eval_res.passed
        assert "exceeds 25% cluster cap" in (eval_res.rejection_reason or "")

    def test_gate_12_refuses_daily_drawdown_circuit_breaker(self):
        """Must halt all new orders if session drawdown >= 3.0%."""
        risk = RiskGateService(starting_capital=1_000_000.0)
        # Session realized loss of ₹35,000 (-3.5% on ₹10L starting capital)
        eval_res = risk.evaluate_order_risk(
            symbol="RELIANCE", order_margin=50_000.0, current_equity=965_000.0,
            open_positions=[], session_realized_pnl=-35_000.0, session_unrealized_pnl=0.0
        )
        assert not eval_res.passed
        assert eval_res.circuit_breaker_active
        assert "Session drawdown" in (eval_res.rejection_reason or "")

    def test_gate_13_refuses_directional_conflict(self):
        """Must refuse trade (NO TRADE) when high conviction bullish and bearish signals conflict."""
        # Confluence magnitude >= 60 with low directional score (< 30)
        factors = {
            "G1": [
                FactorSignal("Bullish VWAP", "BULLISH", 90.0, "vwap"),
            ],
            "G2": [
                FactorSignal("Bearish OI Surge", "BEARISH", 90.0, "oi_surge"),
            ],
            "G3": [
                FactorSignal("Bullish Order Block", "BULLISH", 85.0, "smc"),
            ],
            "G4": [
                FactorSignal("Bearish Institutional Block", "BEARISH", 85.0, "block_deal"),
            ],
        }
        res = master_confluence_engine.evaluate_confluence("RELIANCE", factors)
        assert res.has_conflict
        assert res.decision == "NO TRADE"
        assert "Directional Conflict" in (res.conflict_reason or "")
