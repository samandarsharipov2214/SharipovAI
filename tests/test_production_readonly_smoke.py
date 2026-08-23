from __future__ import annotations

from fastapi.testclient import TestClient

import dashboard


def test_fresh_production_app_readonly_smoke_is_fail_closed(monkeypatch) -> None:
    """Exercise safe production entrypoints beyond route-presence/liveness checks."""

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)

    app = dashboard.create_production_app()
    with TestClient(app, follow_redirects=False) as client:
        startup = client.get("/startup")
        health = client.get("/api/system/health")
        recovery = client.get("/api/system/recovery-plan")
        docs = client.get("/docs")
        openapi = client.get("/openapi.json")

    assert startup.status_code == 200
    assert startup.json() == {"status": "ok", "app": "SharipovAI OS"}

    for response in (health, recovery):
        assert response.status_code == 401
        assert response.json() == {
            "status": "unauthorized",
            "detail": "authentication required",
        }

    assert docs.status_code == 404
    assert openapi.status_code == 404
