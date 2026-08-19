import pytest
from fastapi.testclient import TestClient
from ai_sentinel import AISentinelEngine, ai_sentinel
from app import app

client = TestClient(app)

def test_system_health_endpoint():
    res = client.get("/api/system/health")
    assert res.status_code == 200
    data = res.json()
    assert "health" in data
    assert "score" in data["health"]
    assert "status" in data["health"]

def test_system_heal_endpoint():
    res = client.post("/api/system/heal")
    assert res.status_code == 200
    data = res.json()
    assert "timestamp" in data
    assert "actions_taken" in data

def test_system_logs_endpoint():
    res = client.get("/api/system/logs")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert "total" in data

def test_ai_sentinel_diagnostic_vitality_downgrade():
    sentinel = AISentinelEngine()
    diag = sentinel.run_full_diagnostic_suite()
    assert "composite_score" in diag
    assert "categories" in diag
    assert 0 <= diag["composite_score"] <= 100

def test_ai_sentinel_idempotent_healing_pass():
    sentinel = AISentinelEngine()
    res1 = sentinel.run_self_healing_pass(trigger="pytest_heal_1")
    assert "actions_taken" in res1
    res2 = sentinel.run_self_healing_pass(trigger="pytest_heal_2")
    assert "actions_taken" in res2

def test_10_phase_diagnostics_suite():
    sentinel = AISentinelEngine()
    report = sentinel.run_10_phase_diagnostics()
    assert "overall_status" in report
    assert "overall_score" in report
    assert "total_latency_ms" in report
    assert "phases" in report
    assert len(report["phases"]) == 10
    
    # Verify each phase has required telemetry keys
    for p in report["phases"]:
        assert "phase" in p
        assert "name" in p
        assert "target" in p
        assert "latency_ms" in p
        assert "status" in p
        assert "details" in p
        assert "healing_action" in p
        assert p["latency_ms"] >= 0.0

def test_10_phase_diagnostics_endpoint():
    res = client.get("/api/system/health/diagnostics")
    assert res.status_code == 200
    data = res.json()
    assert "phases" in data
    assert len(data["phases"]) == 10
    assert data["total_phases_count"] == 10
    assert data["passed_phases_count"] >= 8
    assert data["overall_status"] in ("OPTIMAL", "DEGRADED", "CRITICAL")

