from __future__ import annotations

from fastapi.testclient import TestClient

from learning.evidence_learning_bridge import record_decision_outcome_and_learn
from learning.evidence_vault import EvidenceVault
from learning.evidence_vault_app import app
from learning.learning_memory import LearningMemory


EVIDENCE = [
    {
        "title": "Official source",
        "source_domain": "sec.gov",
        "source_type": "regulator_docs",
        "url": "https://sec.gov/example",
        "trust_score": 95,
        "summary": "Official regulator document.",
    }
]


def test_evidence_vault_records_decision_and_replay(tmp_path) -> None:
    vault = EvidenceVault(tmp_path / "evidence.sqlite3")

    result = vault.record_decision(
        actor="news_agent",
        decision="WATCH",
        topic="regulation",
        confidence=82,
        risk_level="MEDIUM",
        reason="Official regulatory source requires monitoring.",
        evidence=EVIDENCE,
        policy_status="watch",
    )
    replay = vault.replay_decision(result["decision_id"])

    assert result["status"] == "ok"
    assert replay["status"] == "ok"
    assert replay["decision"]["actor"] == "news_agent"
    assert replay["evidence"][0]["source_domain"] == "sec.gov"
    assert "Sources: sec.gov" in replay["replay"]


def test_evidence_vault_outcome_updates_source_reputation(tmp_path) -> None:
    vault = EvidenceVault(tmp_path / "evidence.sqlite3")
    decision_id = vault.record_decision(
        actor="market_agent",
        decision="WATCH",
        topic="crypto",
        confidence=75,
        risk_level="LOW",
        reason="Source looked reliable.",
        evidence=EVIDENCE,
    )["decision_id"]

    vault.add_outcome(decision_id=decision_id, outcome="confirmed", impact_score=1.0, learning_signal="positive")
    reputation = vault.source_reputation("sec.gov")["sources"][0]

    assert reputation["trust_score"] > 95
    assert reputation["confirmed"] == 1


def test_negative_outcome_creates_learning_lesson(tmp_path) -> None:
    vault = EvidenceVault(tmp_path / "evidence.sqlite3")
    memory = LearningMemory(tmp_path / "learning.sqlite3")
    decision_id = vault.record_decision(
        actor="news_agent",
        decision="WATCH",
        topic="regulation",
        confidence=70,
        risk_level="MEDIUM",
        reason="Trusted a weak source.",
        evidence=[{**EVIDENCE[0], "source_domain": "blog.example", "trust_score": 40}],
    )["decision_id"]

    result = record_decision_outcome_and_learn(
        vault=vault,
        memory=memory,
        decision_id=decision_id,
        outcome="contradicted",
        impact_score=-1.0,
        notes="Source was later contradicted by official data.",
        learning_signal="negative",
    )

    assert result["status"] == "ok"
    assert result["lesson"] is not None
    assert memory.snapshot()["mistake_count"] == 1
    assert memory.snapshot()["lesson_count"] == 1
    assert vault.source_reputation("blog.example")["sources"][0]["contradicted"] == 1


def test_evidence_vault_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_VAULT_DB", str(tmp_path / "evidence.sqlite3"))
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    client = TestClient(app)

    created = client.post(
        "/api/evidence-vault/decisions",
        json={
            "actor": "risk_engine",
            "decision": "WATCH",
            "topic": "risk",
            "confidence": 80,
            "risk_level": "MEDIUM",
            "reason": "Risk check requires watch mode.",
            "evidence": EVIDENCE,
        },
    )
    assert created.status_code == 200
    decision_id = created.json()["decision_id"]

    replay = client.get(f"/api/evidence-vault/decisions/{decision_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "ok"

    outcome = client.post(
        f"/api/evidence-vault/decisions/{decision_id}/outcome",
        json={"outcome": "confirmed", "impact_score": 1.0, "learning_signal": "positive"},
    )
    assert outcome.status_code == 200
    assert outcome.json()["status"] == "ok"

    snapshot = client.get("/api/evidence-vault/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["evidence"]["decision_count"] == 1

    page = client.get("/evidence-vault")
    assert page.status_code == 200
    assert "Память решений" in page.text
