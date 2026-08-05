from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.memory_api import install_memory_api
from storage import ProjectDatabase


def test_memory_health_is_200_and_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMORY_ENABLED", raising=False)
    app = FastAPI()
    app.state.project_database = ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'memory.db'}")
    install_memory_api(app)

    with TestClient(app) as client:
        response = client.get("/api/memory/health")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert response.json()["execution_authority"] is False
    assert not (tmp_path / "memory.db").exists()


def test_context_endpoint_is_empty_when_injection_is_off(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_CONTEXT_INJECTION", "false")
    app = FastAPI()
    app.state.project_database = ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'memory.db'}")
    install_memory_api(app)

    with TestClient(app) as client:
        response = client.post(
            "/api/memory/context",
            json={"agent_id": "risk_engine", "user_id": "owner", "query_text": "drawdown"},
        )

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["execution_authority"] is False
