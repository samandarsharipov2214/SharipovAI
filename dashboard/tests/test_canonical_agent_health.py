from __future__ import annotations

from fastapi.testclient import TestClient

import agent_health
from dashboard.app import create_app


def test_agent_health_never_invents_score_without_evidence(monkeypatch):
    monkeypatch.setattr(
        agent_health,
        "_definitions",
        lambda: [
            agent_health.AgentDefinition(
                "Learning Engine",
                "learning",
                lambda: {"ok": False, "evidence": [], "last_error": "not validated"},
            )
        ],
    )

    snapshot = agent_health.build_agent_health_snapshot()

    assert snapshot["summary"] == {
        "total_bots": 1,
        "active": 0,
        "warnings": 1,
        "working": 0,
        "degraded": 0,
        "unknown": 1,
    }
    bot = snapshot["bots"][0]
    assert bot["status"] == "unknown"
    assert bot["quality_score"] is None
    assert bot["health_score"] is None
    assert bot["last_error"] == "not validated"


def test_agent_health_marks_proven_check_working(monkeypatch):
    monkeypatch.setattr(
        agent_health,
        "_definitions",
        lambda: [
            agent_health.AgentDefinition(
                "Security Guard",
                "security",
                lambda: {
                    "ok": True,
                    "evidence": ["real_orders_blocked_policy"],
                    "last_action": "verified",
                },
            )
        ],
    )

    snapshot = agent_health.build_agent_health_snapshot()

    bot = snapshot["bots"][0]
    assert bot["status"] == "working"
    assert bot["quality_score"] == 70
    assert bot["evidence_count"] == 1
    assert bot["last_action"] == "verified"


def test_agent_health_api_requires_auth_by_default(monkeypatch):
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    client = TestClient(create_app())

    response = client.get("/api/agent-health")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "detail": "authentication required",
    }


def test_agent_health_api_is_exposed_in_explicit_test_mode(monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app())

    response = client.get("/api/agent-health")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "bots" in payload
    assert payload["truth_policy"].startswith("No decorative score")
