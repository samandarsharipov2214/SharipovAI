from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_evidence_vault_endpoints_installed_in_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_VAULT_DB", str(tmp_path / "evidence.sqlite3"))
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    client = TestClient(create_app(runner_factory=DummyRunner))

    created = client.post(
        "/api/evidence-vault/decisions",
        json={
            "actor": "general_controller",
            "decision": "WATCH",
            "topic": "regulation",
            "confidence": 80,
            "risk_level": "MEDIUM",
            "reason": "Test dashboard evidence integration.",
            "evidence": [{"title": "Official", "source_domain": "sec.gov", "trust_score": 95}],
        },
    )
    assert created.status_code == 200
    decision_id = created.json()["decision_id"]

    replay = client.get(f"/api/evidence-vault/decisions/{decision_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "ok"

    page = client.get("/evidence-vault")
    assert page.status_code == 200
    assert 'id="content"' in page.text
    assert 'data-page="evidence"' in page.text
    assert "learning_evidence_reports_v17.js" in page.text


def test_home_exposes_evidence_vault_navigation() -> None:
    response = TestClient(create_app(runner_factory=DummyRunner)).get("/")
    assert response.status_code == 200
    assert 'data-page="evidence"' in response.text
    assert "Хранилище доказательств" in response.text
