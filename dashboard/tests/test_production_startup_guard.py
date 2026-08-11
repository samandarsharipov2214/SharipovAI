from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import dashboard


def test_production_requires_explicit_auth_secret(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="AUTH_SECRET is required"):
        dashboard._require_production_auth_secret()


def test_non_production_may_use_test_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)

    dashboard._require_production_auth_secret()


def test_package_create_app_installs_global_auth_guard(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")

    app = dashboard.create_app()
    with TestClient(app) as client:
        response = client.get("/api/ai-bots")

    assert response.status_code == 401
    assert response.json()["status"] == "unauthorized"
