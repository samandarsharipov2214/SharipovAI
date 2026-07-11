from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.bybit_account_api import install_bybit_account_api


def _app(monkeypatch, *, username: str | None, is_admin: bool) -> FastAPI:
    import dashboard.app as dashboard_app

    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: username)
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: is_admin)
    monkeypatch.setenv("BYBIT_ACCOUNT_SYNC_ENABLED", "0")

    app = FastAPI()
    install_bybit_account_api(app)
    return app


def test_bybit_account_status_rejects_anonymous(monkeypatch):
    with TestClient(_app(monkeypatch, username=None, is_admin=False)) as client:
        response = client.get("/api/exchange/account/status")

    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "unauthorized"


def test_bybit_account_status_rejects_non_admin(monkeypatch):
    with TestClient(_app(monkeypatch, username="member", is_admin=False)) as client:
        response = client.get("/api/exchange/account/status")

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "forbidden"


def test_bybit_account_status_allows_admin(monkeypatch):
    with TestClient(_app(monkeypatch, username="admin", is_admin=True)) as client:
        response = client.get("/api/exchange/account/status")

    assert response.status_code == 200
    assert response.json()["provider"] == "bybit"
