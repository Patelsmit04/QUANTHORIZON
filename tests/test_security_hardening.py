"""
SECURITY HARDENING & OWASP ASVS DEFENSE TEST SUITE
==================================================
Validates:
1. slowapi rate limiting enforcement on sensitive mutating endpoints (/api/lock_picks, /api/evaluate_picks).
2. HTTP 429 Too Many Requests response payload and Retry-After header.
3. .env and credential hygiene (.env in .gitignore, no hardcoded API keys).
4. Broker API credentials load strictly from environment variables.
"""

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from pathlib import Path


@pytest.fixture(scope="module")
def client():
    import app
    # Seed cache store so lock_picks does not trigger external yfinance scans
    app.cache_store["data"] = [{"symbol": "TCS.NS", "signal": "BTST (BUY)"}]
    return TestClient(app.app)


def test_lock_picks_rate_limit_exceeded(client):
    """
    Assert that /api/lock_picks enforces the strict rate limit (5/minute)
    and returns HTTP 429 Too Many Requests when breached.
    """
    with patch("app._run_closing_lock_sequence", return_value={"locked_count": 0}):
        responses = []
        for _ in range(7):
            res = client.post("/api/lock_picks")
            responses.append(res.status_code)

        assert 429 in responses, f"Expected 429 in responses, got {responses}"

        # Verify the 429 payload structure
        res_429 = client.post("/api/lock_picks")
        assert res_429.status_code == 429
        data = res_429.json()
        assert data.get("status") == "RATE_LIMITED"
        assert "Rate limit exceeded" in data.get("detail", "")
        assert "Retry-After" in res_429.headers


def test_evaluate_picks_rate_limit_exceeded(client):
    """
    Assert that /api/evaluate_picks enforces the strict rate limit (5/minute)
    and returns HTTP 429 Too Many Requests when breached.
    """
    with patch("app.run_daily_evaluation", return_value={"trades_evaluated": 0}):
        responses = []
        for _ in range(7):
            res = client.post("/api/evaluate_picks")
            responses.append(res.status_code)

        assert 429 in responses, f"Expected 429 in responses, got {responses}"


def test_env_file_is_git_ignored():
    """
    Verify .env and .env.* are strictly ignored in .gitignore
    to prevent accidental credential check-ins.
    """
    repo_root = Path(__file__).resolve().parent.parent
    gitignore_path = repo_root / ".gitignore"
    assert gitignore_path.exists(), ".gitignore must exist"

    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]

    assert ".env" in lines, ".env must be explicitly in .gitignore"
    assert ".env.*" in lines, ".env.* must be explicitly in .gitignore"


def test_no_hardcoded_broker_credentials():
    """
    Verify broker providers (e.g. Angel One SmartAPI, etc.) read credentials
    strictly from os.environ and have no fallback default hardcoded credentials.
    """
    from angel_one_provider import get_credentials
    api_key, client_id, password, totp_secret = get_credentials()

    # If env vars are not set, values must be empty string, NOT a hardcoded fallback string
    if not os.environ.get("ANGEL_API_KEY"):
        assert api_key == ""
    if not os.environ.get("ANGEL_CLIENT_ID"):
        assert client_id == ""
    if not os.environ.get("ANGEL_PASSWORD"):
        assert password == ""
    if not os.environ.get("ANGEL_TOTP_SECRET"):
        assert totp_secret == ""


def test_sentry_dsn_safe_exposure(client):
    """
    Verify /api/sentry_dsn only exposes client-safe DSN info, never secret keys or tokens.
    """
    res = client.get("/api/sentry_dsn")
    assert res.status_code == 200
    data = res.json()
    assert "dsn" in data
    assert "environment" in data
    assert "release" in data
    # Ensure no internal secrets leaked
    assert "secret" not in str(data).lower()
    assert "password" not in str(data).lower()
