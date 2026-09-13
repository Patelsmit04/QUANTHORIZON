"""
Regression tests for Evaluation Engine: Direction Mismatch & False Win Sanity Guards
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from evaluation_engine import (
    evaluate_trade_outcome,
    enforce_direction_sanity,
    is_buy_signal,
    is_sell_signal,
    BTST_JACKPOT_THRESHOLD,
    BTST_WIN_THRESHOLD,
    STBT_JACKPOT_THRESHOLD,
    STBT_WIN_THRESHOLD,
)


class TestAccuracyEvaluationGuards:
    """Covers Phase 2 requirements: regression guards against false wins and direction mismatches."""

    def test_btst_negative_gap_is_strictly_loss(self):
        """User requirement: evaluate_outcome(signal='BTST (BUY)', predicted_close=100, actual_open=95)
        must return LOSS, never WIN or JACKPOT WIN."""
        res = evaluate_trade_outcome(
            signal="BTST (BUY)",
            close_price_325=100.0,
            open_price_915=95.0,
            predicted_gap_pct=1.0,
            symbol="TEST_STOCK",
        )
        assert res["outcome"] == "LOSS"
        assert res["gap_pct"] == -5.0
        assert "WIN" not in res["outcome"]

    def test_btst_small_negative_gap_is_strictly_loss(self):
        """BTST with gap < -0.3% (e.g. -0.96% like real Kotak Bank) must be LOSS."""
        res = evaluate_trade_outcome(
            signal="BTST (BUY)",
            close_price_325=416.55,
            open_price_915=412.55,
            predicted_gap_pct=2.1,
            symbol="KOTAKBANK",
        )
        assert res["outcome"] == "LOSS"
        assert res["gap_pct"] == -0.96

    def test_stbt_positive_gap_is_strictly_loss(self):
        """STBT (SELL) with positive gap must be LOSS, never WIN."""
        res = evaluate_trade_outcome(
            signal="STBT (SELL)",
            close_price_325=100.0,
            open_price_915=105.0,
            predicted_gap_pct=-1.5,
            symbol="TEST_STOCK",
        )
        assert res["outcome"] == "LOSS"
        assert res["gap_pct"] == 5.0
        assert "WIN" not in res["outcome"]

    def test_btst_win_thresholds(self):
        """Test legitimate BTST wins."""
        # 1.8% gap -> JACKPOT WIN
        res_jackpot = evaluate_trade_outcome("BTST (BUY)", 100.0, 101.8, 1.5, "WINNER")
        assert res_jackpot["outcome"] == "JACKPOT WIN"

        # 0.8% gap -> WIN
        res_win = evaluate_trade_outcome("BTST (BUY)", 100.0, 100.8, 1.0, "WINNER")
        assert res_win["outcome"] == "WIN"

        # 0.1% gap -> NEUTRAL
        res_neutral = evaluate_trade_outcome("BTST (BUY)", 100.0, 100.1, 0.5, "FLAT")
        assert res_neutral["outcome"] == "NEUTRAL"

    def test_stbt_win_thresholds(self):
        """Test legitimate STBT wins."""
        # -1.8% gap -> JACKPOT WIN
        res_jackpot = evaluate_trade_outcome("STBT (SELL)", 100.0, 98.2, -1.5, "WINNER")
        assert res_jackpot["outcome"] == "JACKPOT WIN"

        # -0.8% gap -> WIN
        res_win = evaluate_trade_outcome("STBT (SELL)", 100.0, 99.2, -1.0, "WINNER")
        assert res_win["outcome"] == "WIN"

        # -0.1% gap -> NEUTRAL
        res_neutral = evaluate_trade_outcome("STBT (SELL)", 100.0, 99.9, -0.5, "FLAT")
        assert res_neutral["outcome"] == "NEUTRAL"

    def test_implausible_outlier_gap_flagged_as_data_anomaly(self):
        """Overnight gap of 265% (Kotak Bank bug case) or 7600% (Reliance mock bug) must be DATA_ANOMALY,
        never graded as a win."""
        res = evaluate_trade_outcome(
            signal="BTST (BUY)",
            close_price_325=416.55,
            open_price_915=1521.10,
            predicted_gap_pct=2.1,
            symbol="KOTAKBANK",
        )
        assert res["outcome"] == "DATA_ANOMALY"
        assert res["is_anomaly"] is True
        assert res["review_required"] is True
        assert "WIN" not in res["outcome"]

    def test_enforce_direction_sanity_forces_loss_on_tampered_outcome(self):
        """Circuit breaker: If someone attempts to pass outcome='JACKPOT WIN' with gap=-5.0% for BUY,
        enforce_direction_sanity immediately overrides and forces LOSS."""
        forced = enforce_direction_sanity("BTST (BUY)", gap_pct=-5.0, outcome="JACKPOT WIN", symbol="TAMPERED")
        assert forced == "LOSS"

        forced_sell = enforce_direction_sanity("STBT (SELL)", gap_pct=5.0, outcome="WIN", symbol="TAMPERED")
        assert forced_sell == "LOSS"

    def test_non_positive_prices_fail_loud_without_crashing(self):
        """Price <= 0 produces DATA_ANOMALY, preventing division by zero."""
        res = evaluate_trade_outcome("BTST (BUY)", 0.0, 100.0, 1.0, "ZERO_CLOSE")
        assert res["outcome"] == "DATA_ANOMALY"

        res2 = evaluate_trade_outcome("BTST (BUY)", 100.0, -5.0, 1.0, "NEG_OPEN")
        assert res2["outcome"] == "DATA_ANOMALY"
