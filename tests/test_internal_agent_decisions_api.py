from __future__ import annotations

import importlib.util
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


def _payload(**overrides):
    value = {
        "decision_id": "decision-001",
        "action": "apply_approved_patch",
        "status": "applied",
        "phase": "complete",
        "message": "approved patch applied and health verified",
        "base_sha": "a" * 40,
        "patch_sha256": "b" * 64,
        "commit_sha": "c" * 40,
        "health_verified": True,
    }
    value.update(overrides)
    return value


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'project.db'}")
    monkeypatch.setenv("SHARIPOVAI_SERVICE_TOKEN", "service-secret")
    app = FastAPI()
    install_internal_agent_decisions_api(app)
    install_internal_agent_decisions_api(app)
    assert "/internal/agent-decisions" not in app.openapi().get("paths", {})
    return TestClient(app, client=("127.0.0.1", 50123))


def test_records_agent_decision_in_canonical_namespace(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/internal/agent-decisions",
        headers={"X-SharipovAI-Service-Token": "service-secret"},
        json=_payload(),
    )
    assert response.status_code == 200
    assert response.json()["idempotent"] is False

    record = ProjectDatabase().get_json("agent_decisions", "decision-001")
    assert record is not None
    assert record["value"]["status"] == "applied"
    assert record["value"]["source"] == "self-healing-run"


def test_idempotent_retry_and_conflict(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    headers = {"X-SharipovAI-Service-Token": "service-secret"}
    first = client.post("/internal/agent-decisions", headers=headers, json=_payload())
    second = client.post("/internal/agent-decisions", headers=headers, json=_payload())
    conflict = client.post(
        "/internal/agent-decisions",
        headers=headers,
        json=_payload(status="reverted", phase="health", message="reverted"),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert conflict.status_code == 409


def test_requires_loopback_service_auth(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    missing = client.post("/internal/agent-decisions", json=_payload())
    assert missing.status_code == 401

    remote_app = FastAPI()
    install_internal_agent_decisions_api(remote_app)
    remote = TestClient(remote_app, client=("192.0.2.10", 50123))
    denied = remote.post(
        "/internal/agent-decisions",
        headers={"X-SharipovAI-Service-Token": "service-secret"},
        json=_payload(),
    )
    assert denied.status_code == 403
