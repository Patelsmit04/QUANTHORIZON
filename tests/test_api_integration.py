"""
Phase 6 integration check for the M7 audit fixes: confirms the strategy_manager validation
changes actually surface correctly through the real FastAPI routes (HTTPException wiring),
not just when called directly as Python functions.

Uses TestClient WITHOUT the `with` context-manager form deliberately — that form fires the
`startup` event, which spawns the real background scheduler threads (market scans, live
network calls). We only want route dispatch here.
"""
import pytest
from fastapi.testclient import TestClient

import app as appmod
import strategy_manager as sm


@pytest.fixture(autouse=True)
def isolated_strategies_store(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "STRATEGIES_FILE", str(tmp_path / "strategies.json"))
    yield


@pytest.fixture
def client():
    return TestClient(appmod.app)


def test_get_strategies_lists_untouched_default(client):
    r = client.get("/api/strategies")
    assert r.status_code == 200
    default = next(s for s in r.json()["strategies"] if s["id"] == "default-5-pillar")
    assert default["active_pillars"]["Pillar 1: Futures OI"] is True
    assert default["required_weight_override"] is None


def test_put_builtin_strategy_pillar_change_rejected(client):
    sm._seed_default_strategy_if_missing()  # isolated store starts empty; seed before mutating
    r = client.put("/api/strategies/default-5-pillar", json={"active_pillars": {"Pillar 1: Futures OI": False}})
    assert r.status_code == 400
    assert "cannot be changed" in r.json()["detail"]


def test_post_strategy_with_invalid_weight_override_rejected(client):
    r = client.post("/api/strategies", json={"name": "Bad Weight Strategy", "required_weight_override": -2})
    assert r.status_code == 400
    assert "required_weight_override" in r.json()["detail"]


def test_clarification_budget_endpoint_still_works(client):
    r = client.get("/api/strategies/clarification_budget")
    assert r.status_code == 200
