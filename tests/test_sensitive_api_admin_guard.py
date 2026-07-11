from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.bybit_account_api import install_bybit_account_api
from dashboard.execution_stages_api import install_execution_stages_api


def _patch_identity(monkeypatch, *, username: str | None, is_admin: bool) -> None:
    dashboard_app = importlib.import_module("dashboard.app")
    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: username)
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: is_admin)


def _configure_auth(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")


def _account_app(monkeypatch, *, username: str | None, is_admin: bool, configured: bool = True) -> FastAPI:
    _patch_identity(monkeypatch, username=username, is_admin=is_admin)
    if configured:
        _configure_auth(monkeypatch)
    else:
        monkeypatch.delenv("AUTH_SECRET", raising=False)
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("BYBIT_ACCOUNT_SYNC_ENABLED", "0")
    app = FastAPI()
    install_bybit_account_api(app)
    return app


def _execution_app(monkeypatch, tmp_path, *, username: str | None, is_admin: bool) -> FastAPI:
    _patch_identity(monkeypatch, username=username, is_admin=is_admin)
    _configure_auth(monkeypatch)
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "execution-journal.json"))
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    app = FastAPI()
    install_execution_stages_api(app)
    return app


def test_sensitive_endpoints_fail_closed_when_auth_is_unconfigured(monkeypatch) -> None:
    with TestClient(_account_app(monkeypatch, username="admin", is_admin=True, configured=False)) as client:
        response = client.get("/api/exchange/account/status")
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "auth_not_configured"


def test_account_endpoints_reject_anonymous(monkeypatch) -> None:
    with TestClient(_account_app(monkeypatch, username=None, is_admin=False)) as client:
        responses = [
            client.get("/api/exchange/account/status"),
            client.get("/api/exchange/account/snapshot"),
            client.post("/api/exchange/account/sync"),
        ]
    assert all(response.status_code == 401 for response in responses)


def test_account_endpoints_reject_non_admin(monkeypatch) -> None:
    with TestClient(_account_app(monkeypatch, username="member", is_admin=False)) as client:
        responses = [
            client.get("/api/exchange/account/status"),
            client.get("/api/exchange/account/snapshot"),
            client.post("/api/exchange/account/sync"),
        ]
    assert all(response.status_code == 403 for response in responses)


def test_admin_can_read_account_status(monkeypatch) -> None:
    with TestClient(_account_app(monkeypatch, username="admin", is_admin=True)) as client:
        response = client.get("/api/exchange/account/status")
    assert response.status_code == 200
    assert response.json()["provider"] == "bybit"


def test_execution_endpoints_reject_anonymous_before_body_parsing(monkeypatch, tmp_path) -> None:
    with TestClient(_execution_app(monkeypatch, tmp_path, username=None, is_admin=False)) as client:
        status_response = client.get("/api/execution/stage-status")
        empty_response = client.post("/api/execution/testnet-order")
        malformed_response = client.post(
            "/api/execution/testnet-order",
            content="{not-json",
            headers={"content-type": "application/json"},
        )
    assert status_response.status_code == 401
    assert empty_response.status_code == 401
    assert malformed_response.status_code == 401


def test_execution_endpoints_reject_non_admin(monkeypatch, tmp_path) -> None:
    with TestClient(_execution_app(monkeypatch, tmp_path, username="member", is_admin=False)) as client:
        status_response = client.get("/api/execution/stage-status")
        order_response = client.post("/api/execution/testnet-order", json={})
    assert status_response.status_code == 403
    assert order_response.status_code == 403


def test_admin_can_read_execution_status(monkeypatch, tmp_path) -> None:
    with TestClient(_execution_app(monkeypatch, tmp_path, username="admin", is_admin=True)) as client:
        response = client.get("/api/execution/stage-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"]["live_execution_enabled"] is False
    assert payload["execution"]["testnet_execution_enabled"] is False
    assert payload["execution"]["kill_switch"] is True
