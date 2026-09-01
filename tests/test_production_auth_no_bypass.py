from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import dashboard
from dashboard.global_auth_guard import auth_disabled


@pytest.mark.parametrize(
    ("environment", "render"),
    (("production", None), ("prod", None), (None, "1")),
)
def test_all_supported_production_signals_ignore_auth_bypass_flag(
    monkeypatch,
    environment: str | None,
    render: str | None,
) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    if environment is not None:
        monkeypatch.setenv("ENVIRONMENT", environment)
    if render is not None:
        monkeypatch.setenv("RENDER", render)
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")

    assert auth_disabled() is False


@pytest.mark.parametrize(
    ("environment", "render"),
    (("production", None), ("prod", None), (None, "1")),
)
def test_fresh_production_app_rejects_anonymous_private_api_for_every_production_signal(
    monkeypatch,
    environment: str | None,
    render: str | None,
) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    if environment is not None:
        monkeypatch.setenv("ENVIRONMENT", environment)
    if render is not None:
        monkeypatch.setenv("RENDER", render)
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")

    app = dashboard.create_production_app()
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/system/release-truth")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "detail": "authentication required",
    }



def test_site_v1_root_is_public_while_app_route_remains_authenticated(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    app = dashboard.create_production_app()

    with TestClient(app, follow_redirects=False) as client:
        root = client.get("/")
        login = client.get("/login")
        private_app = client.get("/app")

    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")
    assert "/static/site-v1/site.css" in root.text
    assert "access-card" in root.text
    assert "SharipovAI Login" not in root.text
    assert "Обзор" not in root.text
    assert login.status_code == 303
    assert login.headers["location"] == "/?mode=login"
    assert private_app.status_code == 303
    assert private_app.headers["location"] == "/login?next=/app"
