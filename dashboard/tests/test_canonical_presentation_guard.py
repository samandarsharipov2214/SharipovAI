from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import canonical_presentation_guard as guard


class _Monitor:
    def snapshot(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "organs": [
                {
                    "organ_id": "risk_engine",
                    "responsibility": "risk",
                    "status": "healthy",
                    "checked_at_ms": 1_000,
                    "blockers": [],
                    "evidence": ["canonical-risk-evidence"],
                }
            ],
        }


class _Loop:
    def snapshot(self) -> dict[str, object]:
        return {"status": "ok"}


def test_ai_bots_surface_ignores_inner_fabricated_status() -> None:
    app = FastAPI()
    app.state.ai_organ_runtime_monitor = _Monitor()

    @app.get("/api/ai-bots")
    def fake_bots() -> dict[str, object]:
        return {"summary": {"active": 99}, "bots": [{"name": "Fake AI", "status": "working"}]}

    guard.install_canonical_presentation_guard(app)
    with TestClient(app) as client:
        response = client.get("/api/ai-bots")

    payload = response.json()
    assert response.status_code == 200
    assert payload["summary"]["active"] == 1
    assert payload["summary"]["canonical_ai_count"] == 1
    assert payload["bots"][0]["id"] == "risk_engine"
    assert payload["bots"][0]["last_action"] == "canonical-risk-evidence"


def test_canonical_demo_read_and_mutation_boundary(monkeypatch) -> None:
    app = FastAPI()
    app.state.autonomous_paper_loop = _Loop()
    monkeypatch.setattr(
        guard,
        "load_canonical_paper_state",
        lambda: {
            "status": "ok",
            "source_of_truth": "ProjectDatabase/CouncilAuthorizedPaperLoop",
            "cash": 9_500.0,
            "real_orders_blocked": True,
        },
    )

    @app.get("/api/demo/state")
    def fake_state() -> dict[str, object]:
        return {"cash": 999_999.0, "source": "fake"}

    @app.post("/api/demo/reset")
    def fake_reset() -> dict[str, bool]:
        return {"mutated": True}

    guard.install_canonical_presentation_guard(app)
    with TestClient(app) as client:
        state = client.get("/api/demo/state")
        reset = client.post("/api/demo/reset")

    assert state.status_code == 200
    assert state.json()["state"]["cash"] == 9_500.0
    assert state.json()["source_of_truth"] == "ProjectDatabase/CouncilAuthorizedPaperLoop"
    assert reset.status_code == 410
    assert reset.json()["mutation_performed"] is False


def test_chat_surface_is_presentation_only_and_does_not_call_inner_runner(monkeypatch) -> None:
    app = FastAPI()
    inner_called = {"value": False}
    monkeypatch.setattr(
        guard,
        "load_canonical_paper_state",
        lambda: {
            "status": "ok",
            "source_of_truth": "ProjectDatabase/CouncilAuthorizedPaperLoop",
            "last_action": "WAIT",
        },
    )
    monkeypatch.setattr(
        guard,
        "answer_chat",
        lambda message, state: {
            "status": "ok",
            "reply": f"canonical:{message}",
            "intent": "overview",
            "source_ai": "General Controller",
            "data": {"source": state["source_of_truth"]},
        },
    )

    @app.post("/api/chat/message")
    def legacy_chat() -> dict[str, object]:
        inner_called["value"] = True
        return {"reply": "legacy"}

    guard.install_canonical_presentation_guard(app)
    with TestClient(app) as client:
        response = client.post("/api/chat/message", json={"message": "status"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["reply"] == "canonical:status"
    assert payload["run"]["decision"] == "WAIT"
    assert payload["presentation_only"] is True
    assert payload["mutation_performed"] is False
    assert inner_called["value"] is False
