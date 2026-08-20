from __future__ import annotations

from fastapi.testclient import TestClient

import dashboard
from dashboard.global_auth_guard import auth_disabled


def test_production_environment_ignores_auth_bypass_flag(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")

    assert auth_disabled() is False


def test_fresh_production_app_rejects_anonymous_private_api_even_with_bypass_flag(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")

    app = dashboard.create_production_app()
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/system/release-truth")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "detail": "authentication required",
    }
