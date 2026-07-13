from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.global_auth_guard import auth_disabled, install_global_auth_guard


def _app(monkeypatch, *, username: str | None = None) -> FastAPI:
    dashboard_app = importlib.import_module("dashboard.app")
    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: username)
    app = FastAPI()

    @app.get("/")
    def root() -> dict[str, str]:
        return {"status": "private"}

    @app.get("/api/private")
    def private_api() -> dict[str, str]:
        return {"status": "private"}

    @app.get("/private-page")
    def private_page() -> dict[str, str]:
        return {"status": "private"}

    install_global_auth_guard(app)
    return app


def test_auth_is_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    assert auth_disabled() is False


def test_bypass_requires_explicit_true_value(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    assert auth_disabled() is False
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    assert auth_disabled() is True


def test_root_is_private_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    with TestClient(_app(monkeypatch), follow_redirects=False) as client:
        response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/"


def test_private_api_rejects_anonymous(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    with TestClient(_app(monkeypatch)) as client:
        response = client.get("/api/private")
    assert response.status_code == 401
    assert response.json()["status"] == "unauthorized"


def test_private_page_redirects_anonymous_to_login(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    with TestClient(_app(monkeypatch), follow_redirects=False) as client:
        response = client.get("/private-page")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/private-page"


def test_authenticated_session_can_access_private_route(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    with TestClient(_app(monkeypatch, username="admin")) as client:
        response = client.get("/api/private")
    assert response.status_code == 200


def test_explicit_test_bypass_does_not_change_default(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    with TestClient(_app(monkeypatch)) as client:
        response = client.get("/api/private")
    assert response.status_code == 200
