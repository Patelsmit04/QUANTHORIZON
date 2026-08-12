"""
M9 audit fix: every mutating endpoint (strategy CRUD, lock/evaluate picks, execute, run index
intelligence, mark notifications read) previously had zero authentication. require_api_key()
gates them behind a shared secret (TRADEXO_API_KEY) when configured, while staying a no-op
(today's fully-open behavior) when it isn't — preserving backward compatibility for anyone who
hasn't opted in yet.
"""
import pytest
from fastapi.testclient import TestClient

import app as appmod
import strategy_manager as sm


@pytest.fixture
def client():
    return TestClient(appmod.app)


@pytest.fixture(autouse=True)
def isolated_strategies_store(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "STRATEGIES_FILE", str(tmp_path / "strategies.json"))
    sm._seed_default_strategy_if_missing()  # isolated store starts empty
    yield


def test_require_api_key_is_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "")
    appmod.require_api_key(x_api_key=None)  # must not raise


def test_require_api_key_rejects_missing_header_when_configured(monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "s3cr3t")
    with pytest.raises(Exception) as exc_info:
        appmod.require_api_key(x_api_key=None)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_require_api_key_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "s3cr3t")
    with pytest.raises(Exception) as exc_info:
        appmod.require_api_key(x_api_key="wrong")
    assert getattr(exc_info.value, "status_code", None) == 401


def test_require_api_key_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "s3cr3t")
    appmod.require_api_key(x_api_key="s3cr3t")  # must not raise


def test_mutating_endpoint_401s_without_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "s3cr3t")
    r = client.put("/api/strategies/default-5-pillar", json={"description": "x"})
    assert r.status_code == 401


def test_mutating_endpoint_succeeds_with_correct_key(client, monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "s3cr3t")
    r = client.put(
        "/api/strategies/default-5-pillar",
        json={"description": "x"},
        headers={"X-API-Key": "s3cr3t"},
    )
    assert r.status_code == 200


def test_mutating_endpoint_open_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "")
    r = client.put("/api/strategies/default-5-pillar", json={"description": "x"})
    assert r.status_code == 200  # today's fully-open behavior, unchanged


def test_read_endpoints_never_require_a_key(client, monkeypatch):
    monkeypatch.setattr(appmod, "TRADEXO_API_KEY", "s3cr3t")
    r = client.get("/api/strategies")
    assert r.status_code == 200
