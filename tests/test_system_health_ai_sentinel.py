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
