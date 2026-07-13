from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.local_audit_api import install_local_audit_api


def test_local_audit_returns_sanitized_read_only_evidence(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    app = FastAPI()
    install_local_audit_api(app)

    response = TestClient(app).get("/api/system/local-audit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["read_only"] is True
    assert payload["loopback_verified"] is True
    assert payload["execution"] == {
        "kill_switch": True,
        "live_enabled": False,
        "testnet_enabled": False,
        "mode": "sandbox",
    }
    serialized = response.text.lower()
    assert "api_secret" not in serialized
    assert "password" not in serialized
    assert "auth_secret" not in serialized


def test_local_audit_denies_non_loopback_client(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    app = FastAPI()
    install_local_audit_api(app)
    client = TestClient(app, client=("203.0.113.5", 50000))

    response = client.get("/api/system/local-audit")

    assert response.status_code == 403
    assert response.json()["status"] == "forbidden"
