"""
TEST SUITE FOR GOLDEN PATH ACCURACY & SENTINEL RACE GUARDS
==============================================================================
Tests:
1. Golden path probe execution and log recording.
2. Live index price accuracy probe in AI Sentinel.
3. Closing sequence pre-snapshot scan freshness guard.
4. Sentinel Step 5 idempotency with closing_sequence_state.json.
==============================================================================
"""

import os
import json
import pytest
from golden_path_logger import golden_path_monitor, GOLDEN_PATH_LOG_FILE
from ai_sentinel import AISentinelEngine
from env_utils import DATA_DIR


def test_golden_path_probe_execution():
    """Verifies that golden path executes accuracy probes and logs comparisons."""
    probe = golden_path_monitor.execute_accuracy_probe()
    assert isinstance(probe, dict)
    assert "timestamp" in probe
    assert "indices" in probe
    assert "latency_ms" in probe

    golden_path_monitor._record_probe(probe)
    summary = golden_path_monitor.get_summary()
    assert summary["total_probes"] >= 1
    assert "recent_probes" in summary


def test_sentinel_live_index_accuracy_probe():
    """Verifies that the sentinel index accuracy probe runs without error."""
    sentinel = AISentinelEngine()
    findings = sentinel._probe_live_index_accuracy()
    assert isinstance(findings, list)


def test_sentinel_step5_idempotency_with_closing_sequence():
    """Verifies that Step 5 respects closing_sequence_state.json lock_done flag."""
    sentinel = AISentinelEngine()
    cs_state_file = os.path.join(DATA_DIR, "closing_sequence_state.json")

    original_state = None
    if os.path.exists(cs_state_file):
        with open(cs_state_file, "r", encoding="utf-8") as f:
            original_state = f.read()

    try:
        from env_utils import get_ist_now
        today_str = get_ist_now().strftime("%Y-%m-%d")

        # Mock closing sequence already locked 5 picks today
        mock_cs = {
            "date": today_str,
            "lock_done": True,
            "lock_result": {"locked_count": 5}
        }
        with open(cs_state_file, "w", encoding="utf-8") as f:
            json.dump(mock_cs, f)

        # Sentinel should skip Step 5 (returns empty actions)
        actions = sentinel._heal_step5_reconcile_closing_lock()
        assert len(actions) == 0
    finally:
        if original_state:
            with open(cs_state_file, "w", encoding="utf-8") as f:
                f.write(original_state)
