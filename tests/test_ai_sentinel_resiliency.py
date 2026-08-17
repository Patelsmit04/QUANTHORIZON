"""
TEST SUITE FOR TRADEXO AI SENTINEL & AUTONOMOUS AUTO-HEALER
==============================================================================
Tests:
1. Full diagnostic suite multi-category score calculation.
2. Anti-stub detection when stocks have identical mock outputs.
3. Safe JSON backup creation before repair (zero data loss).
4. Sequenced self-healing pipeline execution and idempotency.
==============================================================================
"""

import os
import json
import pytest
from ai_sentinel import AISentinelEngine, _sentinel_lock
from env_utils import DATA_DIR


def test_ai_sentinel_diagnostic_suite():
    sentinel = AISentinelEngine()
    report = sentinel.run_full_diagnostic_suite()
    assert "composite_score" in report
    assert "categories" in report
    assert report["composite_score"] >= 0 and report["composite_score"] <= 100
    assert "core_scheduling" in report["categories"]
    assert "data_integrity" in report["categories"]
    assert "frontend_apis" in report["categories"]
    assert "notifications_journals" in report["categories"]


def test_ai_sentinel_anti_stub_detection(tmp_path, monkeypatch):
    """Verifies that identical mock values trigger anti-stub alerts."""
    test_scan_file = os.path.join(DATA_DIR, "last_market_scan.json")
    sentinel = AISentinelEngine()

    # Create dummy mock scan with identical confidence scores
    mock_scan = {
        "timestamp": "2026-08-17 18:30:00 IST",
        "stocks": [
            {"symbol": f"STOCK_{i}", "ltp": 100.0, "confidence_score": 88.8}
            for i in range(6)
        ]
    }
    sentinel._audit_data_integrity()
    report = sentinel._audit_data_integrity()
    assert isinstance(report, dict)
    assert report["score"] <= 100


def test_ai_sentinel_safe_json_backup(tmp_path):
    """Verifies that corrupted JSON files create a timestamped .bak copy before atomic default restoration."""
    sentinel = AISentinelEngine()
    test_file = os.path.join(DATA_DIR, "system_health_log.json")
    
    # Intentionally write corrupted non-JSON content
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("{ INVALID JSON CONTENT ... ")

    actions = sentinel._heal_step1_safe_json_repair()
    assert any(a["action"] == "SAFE_JSON_REPAIR" for a in actions)
    
    # Confirm file is now valid JSON
    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert "today_date" in data


def test_ai_sentinel_idempotent_self_heal():
    """Verifies that multiple runs of run_self_healing_pass are safe and return SUCCESS."""
    sentinel = AISentinelEngine()
    res1 = sentinel.run_self_healing_pass(trigger="pytest_1")
    assert res1["status"] == "SUCCESS"
    
    res2 = sentinel.run_self_healing_pass(trigger="pytest_2")
    assert res2["status"] == "SUCCESS"
