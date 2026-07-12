from __future__ import annotations

import pytest

from meta_ai import AgentOpinion, PredictionOutcome
from meta_ai_adapter import record_realized_result
from meta_ai_persistence import MetaAIPersistenceError, PersistentMetaAI
from storage import ProjectDatabase, VersionConflict


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'meta-ai.db'}")
    database.initialize()
    return database


def _outcome(agent_id: str = "Market AI", *, pnl: float = 2.5) -> PredictionOutcome:
    return PredictionOutcome(
        agent_id=agent_id,
        predicted_action="BUY",
        realized_action="BUY",
        confidence=0.8,
        pnl_contribution=pnl,
        drawdown_contribution=0.2,
        regime="bull",
    )


def test_reputation_survives_restart(tmp_path) -> None:
    database = _database(tmp_path)
    first = PersistentMetaAI(database)
    assert first.record_outcomes([_outcome()], decision_id="decision-1") is True

    restarted = PersistentMetaAI(database)
    snapshot = restarted.reputations_snapshot("bull")
    assert snapshot["Market AI"]["total_predictions"] == 1
    assert snapshot["Market AI"]["accuracy"] == 1.0
    assert restarted.persistence_status()["state_version"] == 1


def test_duplicate_decision_id_does_not_double_count(tmp_path) -> None:
    database = _database(tmp_path)
    meta = PersistentMetaAI(database)
    assert meta.record_outcomes([_outcome()], decision_id="decision-duplicate") is True
    assert meta.record_outcomes([_outcome(pnl=100.0)], decision_id="decision-duplicate") is False

    restarted = PersistentMetaAI(database)
    snapshot = restarted.reputations_snapshot("bull")
    assert snapshot["Market AI"]["total_predictions"] == 1
    assert snapshot["Market AI"]["pnl_contribution"] == 2.5


def test_existing_agent_payloads_are_persisted_through_adapter(tmp_path) -> None:
    database = _database(tmp_path)
    meta = PersistentMetaAI(database)
    payloads = [
        {
            "name": "Market AI",
            "decision": "BUY",
            "confidence": 82,
            "data_quality": 91,
            "risk": 24,
            "evidence_class": "verified_market",
        },
        {
            "name": "News AI",
            "decision": "BUY",
            "confidence": 74,
            "data_quality": 85,
            "risk": 30,
            "evidence_class": "verified_market",
        },
    ]

    recorded = record_realized_result(
        meta,
        payloads,
        realized_action="BUY",
        pnl_by_agent={"Market AI": 1.2, "News AI": 0.8},
        regime="bull",
        decision_id="adapter-decision-1",
        evidence_class="verified_market",
        verified_market_data=True,
    )

    assert recorded is True
    snapshot = PersistentMetaAI(database).reputations_snapshot("bull")
    assert snapshot["Market AI"]["total_predictions"] == 1
    assert snapshot["News AI"]["total_predictions"] == 1


def test_persistent_adapter_requires_decision_id(tmp_path) -> None:
    meta = PersistentMetaAI(_database(tmp_path))
    with pytest.raises(MetaAIPersistenceError, match="decision_id"):
        record_realized_result(
            meta,
            [{"name": "Market AI", "decision": "BUY", "confidence": 80}],
            realized_action="BUY",
            regime="bull",
        )


def test_synthetic_outcome_is_rejected(tmp_path) -> None:
    meta = PersistentMetaAI(_database(tmp_path))
    with pytest.raises(MetaAIPersistenceError, match="verified market evidence"):
        meta.record_outcomes(
            [_outcome()],
            decision_id="synthetic-1",
            evidence_class="synthetic_simulation",
            verified_market_data=False,
        )
    assert meta.reputations_snapshot() == {}


def test_concurrent_writer_cannot_silently_overwrite_reputation(tmp_path) -> None:
    database = _database(tmp_path)
    first = PersistentMetaAI(database)
    stale = PersistentMetaAI(database)

    first.record_outcomes([_outcome("Market AI")], decision_id="decision-first")
    with pytest.raises(VersionConflict):
        stale.record_outcomes([_outcome("News AI")], decision_id="decision-stale")

    stale.reload()
    assert stale.record_outcomes([_outcome("News AI")], decision_id="decision-second") is True
    snapshot = PersistentMetaAI(database).reputations_snapshot("bull")
    assert snapshot["Market AI"]["total_predictions"] == 1
    assert snapshot["News AI"]["total_predictions"] == 1


def test_decision_audit_is_immutable_and_idempotent(tmp_path) -> None:
    database = _database(tmp_path)
    meta = PersistentMetaAI(database)
    opinions = [
        AgentOpinion("Market AI", "BUY", 0.8, 0.9, 0.2, "bull"),
        AgentOpinion("News AI", "WAIT", 0.6, 0.8, 0.3, "bull"),
    ]

    first = meta.audit_and_persist(
        "decision-audit-1",
        opinions,
        selected_action="BUY",
        realized_action="BUY",
    )
    second = meta.audit_and_persist(
        "decision-audit-1",
        [],
        selected_action="SELL",
        realized_action="SELL",
    )

    assert first == second
    events = database.list_events(
        "decision_quality",
        entity_type="decision_audit",
        entity_id="decision-audit-1",
        limit=10,
    )
    assert len(events) == 1
    assert events[0]["payload"]["audit"]["selected_action"] == "BUY"


def test_corrupt_persistent_state_fails_closed(tmp_path) -> None:
    database = _database(tmp_path)
    database.set_ai_state(
        "decision_quality.meta_ai",
        {
            "schema_version": 1,
            "processed_decision_ids": [],
            "history": [],
            "reputations": {
                "Market AI": {
                    "agent_id": "Market AI",
                    "total_predictions": 1,
                    "correct_predictions": 2,
                    "confidence_error_sum": 0.0,
                    "pnl_contribution": 0.0,
                    "drawdown_contribution": 0.0,
                    "regime_total": {},
                    "regime_correct": {},
                }
            },
        },
    )
    with pytest.raises(MetaAIPersistenceError, match="cannot exceed"):
        PersistentMetaAI(database)
