from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from storage import ProjectDatabase

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("dashboard")
package.__path__ = [str(ROOT / "dashboard")]
sys.modules.setdefault("dashboard", package)
spec = importlib.util.spec_from_file_location(
    "dashboard.internal_agent_decisions_api",
    ROOT / "dashboard" / "internal_agent_decisions_api.py",
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
install_internal_agent_decisions_api = module.install_internal_agent_decisions_api

BASE_SHA = "a" * 40
PATCH_SHA = "b" * 64
HEADERS = {"X-SharipovAI-Service-Token": "service-secret"}


def _claim(**overrides):
    value = {
        "decision_id": "decision-001",
        "action": "apply_approved_patch",
        "base_sha": BASE_SHA,
        "patch_sha256": PATCH_SHA,
    }
    value.update(overrides)
    return value


def _result(**overrides):
    value = {
        **_claim(),
        "status": "applied",
        "phase": "complete",
        "message": "approved patch applied and health verified",
        "commit_sha": "c" * 40,
        "health_verified": True,
    }
    value.update(overrides)
    return value


def _client(tmp_path, monkeypatch, *, status: str = "approved", verdict: str = "allow"):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'project.db'}")
    monkeypatch.setenv("SHARIPOVAI_SERVICE_TOKEN", "service-secret")
    database = ProjectDatabase()
    database.initialize()
    database.record_agent_decision(
        decision_id="decision-001",
        kind="approve",
        status=status,
        base_sha=BASE_SHA,
        target_branch="main",
        patch_sha256=PATCH_SHA,
        security_verdict=verdict,
        actor="telegram-owner",
        rationale="owner approved bounded repair",
        metadata={"owner_approved": True},
    )
    app = FastAPI()
    install_internal_agent_decisions_api(app)
    install_internal_agent_decisions_api(app)
    paths = app.openapi().get("paths", {})
    assert "/internal/agent-decisions" not in paths
    assert "/internal/agent-decisions/claim" not in paths
    return TestClient(app, client=("127.0.0.1", 50123)), database


def test_claim_requires_existing_owner_and_security_approval(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    response = client.post("/internal/agent-decisions/claim", headers=HEADERS, json=_claim())
    assert response.status_code == 200
    assert response.json()["approved"] is True

    wrong = client.post(
        "/internal/agent-decisions/claim",
        headers=HEADERS,
        json=_claim(patch_sha256="d" * 64),
    )
    assert wrong.status_code == 409


def test_records_terminal_result_in_agent_decisions_and_event(tmp_path, monkeypatch) -> None:
    client, database = _client(tmp_path, monkeypatch)
    response = client.post("/internal/agent-decisions", headers=HEADERS, json=_result())
    assert response.status_code == 200
    assert response.json()["idempotent"] is False

    record = database.get_agent_decision("decision-001")
    assert record is not None
    assert record["status"] == "applied"
    assert record["metadata"]["host_result"]["status"] == "applied"
    with database.connect() as connection:
        row = connection.execute(
            "SELECT event_type, payload_json FROM agent_decision_events WHERE decision_id = ?",
            ("decision-001",),
        ).fetchone()
    assert row is not None
    assert row["event_type"] == "host_applied"
    assert json.loads(row["payload_json"])["health_verified"] is True


def test_reverted_host_commit_records_failed_decision_and_exact_event(tmp_path, monkeypatch) -> None:
    client, database = _client(tmp_path, monkeypatch)
    response = client.post(
        "/internal/agent-decisions",
        headers=HEADERS,
        json=_result(
            status="reverted",
            phase="health",
            message="health verification failed; exact automatic commit reverted",
            health_verified=True,
        ),
    )
    assert response.status_code == 200

    record = database.get_agent_decision("decision-001")
    assert record is not None
    assert record["status"] == "failed"
    assert record["kind"] == "approve"
    assert record["metadata"]["host_result"]["status"] == "reverted"
    with database.connect() as connection:
        row = connection.execute(
            "SELECT event_type FROM agent_decision_events WHERE decision_id = ?",
            ("decision-001",),
        ).fetchone()
    assert row is not None
    assert row["event_type"] == "host_reverted"


def test_exact_retry_is_idempotent_and_conflicting_result_is_rejected(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    first = client.post("/internal/agent-decisions", headers=HEADERS, json=_result())
    second = client.post("/internal/agent-decisions", headers=HEADERS, json=_result())
    conflict = client.post(
        "/internal/agent-decisions",
        headers=HEADERS,
        json=_result(status="reverted", phase="health", message="reverted"),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert conflict.status_code == 409


def test_unapproved_or_unauthenticated_decision_fails_closed(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch, status="pending")
    unapproved = client.post("/internal/agent-decisions/claim", headers=HEADERS, json=_claim())
    assert unapproved.status_code == 409
    missing = client.post("/internal/agent-decisions/claim", json=_claim())
    assert missing.status_code == 401


def test_remote_client_is_rejected(tmp_path, monkeypatch) -> None:
    _, _ = _client(tmp_path, monkeypatch)
    app = FastAPI()
    install_internal_agent_decisions_api(app)
    remote = TestClient(app, client=("192.0.2.10", 50123))
    denied = remote.post("/internal/agent-decisions/claim", headers=HEADERS, json=_claim())
    assert denied.status_code == 403
