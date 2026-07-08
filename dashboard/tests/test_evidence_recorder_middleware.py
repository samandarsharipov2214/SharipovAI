from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app
from learning.evidence_vault import EvidenceVault


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_trade_gate_response_is_recorded_in_evidence_vault(tmp_path, monkeypatch) -> None:
    evidence_db = tmp_path / "evidence.sqlite3"
    monkeypatch.setenv("EVIDENCE_VAULT_DB", str(evidence_db))
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(tmp_path / "policy.json"))
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/trade-gate")

    assert response.status_code == 200
    snapshot = EvidenceVault(evidence_db).snapshot()
    assert snapshot["decision_count"] == 1
    assert snapshot["recent_decisions"][0]["actor"] == "trade_gate"


def test_health_response_is_not_recorded(tmp_path, monkeypatch) -> None:
    evidence_db = tmp_path / "evidence.sqlite3"
    monkeypatch.setenv("EVIDENCE_VAULT_DB", str(evidence_db))
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert EvidenceVault(evidence_db).snapshot()["decision_count"] == 0
