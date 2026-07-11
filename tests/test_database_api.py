from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.database_api import install_database_api, readiness_status
from storage import ProjectDatabase


def test_health_is_public_and_checks_database(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_SECRET", "secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password-long-enough")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'health.db'}")
    app = FastAPI()
    install_database_api(app, database=database)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["database"]["status"] == "ok"
    assert response.json()["configuration"]["kill_switch"] is True


def test_readiness_fails_when_required_config_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    payload = readiness_status(ProjectDatabase(f"sqlite:///{tmp_path / 'health.db'}"))
    assert payload["status"] == "error"
    assert set(payload["configuration"]["missing"]) == {"AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD"}


def test_project_memory_requires_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_SECRET", "secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password-long-enough")
    app = FastAPI()
    install_database_api(app, database=ProjectDatabase(f"sqlite:///{tmp_path / 'memory.db'}"))
    response = TestClient(app).get("/api/project-memory/messages")
    assert response.status_code == 401
