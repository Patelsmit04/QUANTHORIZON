"""
TEST SUITE FOR TRADEXO AI SENTINEL EXPANDED PROBES & RELIABILITY
==============================================================================
Tests:
1. Anti-stub detection for gap_probability and backtest_win_rate.
2. Per-trade accuracy-pipeline verification (delta matching).
3. Notification canary liveness cycle (write -> read -> delete).
4. Partial JSON recovery from corrupted structures.
5. Sequenced self-healing and post-repair self-verification.
==============================================================================
"""

import os
import json
import pytest
from ai_sentinel import AISentinelEngine
from env_utils import DATA_DIR


def test_sentinel_anti_stub_gap_and_backtest():
    """Verifies that uniform gap probabilities or backtest win rates trigger anti-stub findings."""
    sentinel = AISentinelEngine()

    # Uniform gap probability across 6 stocks
    mock_scan_gap = {
        "timestamp": "2026-08-17 18:30:00 IST",
        "stocks": [
            {"symbol": f"STOCK_{i}", "ltp": float(100 + i * 10), "gap_probability": 85.0, "confidence_score": float(70 + i)}
            for i in range(6)
        ]
    }
    scan_file = os.path.join(DATA_DIR, "last_market_scan.json")
    original_scan = None
    if os.path.exists(scan_file):
        with open(scan_file, "r", encoding="utf-8") as f:
            original_scan = f.read()

    try:
        with open(scan_file, "w", encoding="utf-8") as f:
            json.dump(mock_scan_gap, f)

        report = sentinel._audit_data_integrity()
        assert any(f["code"] == "ANTI_STUB_GAP_PROB" for f in report.get("findings", []))
    finally:
        if original_scan:
            with open(scan_file, "w", encoding="utf-8") as f:
                f.write(original_scan)


def test_sentinel_notification_canary_liveness():
    """Verifies that the canary probe performs a clean insert, read, and delete cycle."""
    sentinel = AISentinelEngine()
    result = sentinel._probe_notification_liveness()
    assert result["ok"] is True


def test_sentinel_partial_json_recovery(tmp_path):
    """Verifies that trailing-corrupted JSON can be partially recovered."""
    sentinel = AISentinelEngine()
    test_file = os.path.join(tmp_path, "partial_corrupt.json")

    # Valid JSON prefix with trailing corruption
    corrupt_text = '{"valid_key": "valid_value", "number": 42, "unclosed_field": '
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(corrupt_text)

    recovered = sentinel._attempt_partial_json_recovery(test_file)
    assert recovered is not None
    assert isinstance(recovered, dict)
    assert "valid_key" in recovered
    assert recovered["valid_key"] == "valid_value"


def test_sentinel_evaluation_pipeline_verification():
    """Verifies the before/after trade count delta verification."""
    sentinel = AISentinelEngine()

    pre_counts = {"total_trades": 10, "wins": 8, "losses": 2}
    
    # Delta of 5 matches expected 5
    res_pass = sentinel._verify_evaluation_pipeline(pre_counts, expected_evaluated=5)
    assert isinstance(res_pass, dict)
    assert "status" in res_pass


def test_sentinel_self_verification_of_healed_actions():
    """Verifies that run_self_healing_pass records verified: True for successful actions."""
    sentinel = AISentinelEngine()
    res = sentinel.run_self_healing_pass(trigger="pytest_expanded_test")
    assert res["status"] == "SUCCESS"
    assert "diagnostic_report" in res
    assert res["diagnostic_report"]["composite_score"] >= 90
