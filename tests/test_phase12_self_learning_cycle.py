from __future__ import annotations

import math

import pytest

from learning_engine import OutcomeAttributionService, OutcomeEvidence, SelfLearningSupervisor
from meta_ai_persistence import EVENT_NAMESPACE
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'phase12.db'}")
    database.initialize()
    return database


def _outcome() -> dict[str, object]:
    return {
        "outcome_id": "outcome-1",
        "decision_id": "decision-1",
        "source": "paper",
        "selected_action": "BUY",
        "realized_action": "BUY",
        "net_pnl": 12.5,
        "drawdown_contribution": 2.0,
        "regime": "trend",
        "occurred_at_ms": 1_700_000_000_000,
        "evidence_class": "verified_market",
        "verified_market_data": True,
        "agents": [
            {"agent_id": "market-agent", "action": "BUY", "confidence": 80.0, "evidence_score": 0.9},
            {"agent_id": "risk-agent", "action": "BUY", "confidence": 60.0, "evidence_score": 0.8},
        ],
    }


def test_outcome_attribution_is_idempotent_and_reconciled(tmp_path) -> None:
    service = OutcomeAttributionService(_database(tmp_path))
    first = service.record(_outcome())
    repeated = service.record(_outcome())
    assert first["idempotent"] is False
    assert repeated["idempotent"] is True
    assert first["evidence_sha256"] == repeated["evidence_sha256"]
    assert math.isclose(sum(float(row["pnl_attribution"]) for row in first["attributions"]), 12.5, abs_tol=1e-9)
    assert math.isclose(sum(float(row["drawdown_attribution"]) for row in first["attributions"]), 2.0, abs_tol=1e-9)
    conflicting = _outcome()
    conflicting["net_pnl"] = 13.0
    with pytest.raises(ValueError, match="conflicting outcome evidence"):
        service.record(conflicting)


def test_policy_rejects_synthetic_and_non_finite_evidence() -> None:
    synthetic = _outcome()
    synthetic["evidence_class"] = "synthetic"
    with pytest.raises(ValueError, match="synthetic"):
        OutcomeEvidence.from_mapping(synthetic)
    invalid = _outcome()
    invalid["net_pnl"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        OutcomeEvidence.from_mapping(invalid)


def test_supervisor_ingests_settlement_exactly_once(tmp_path) -> None:
    database = _database(tmp_path)
    database.append_event(
        EVENT_NAMESPACE,
        "decision_assessment",
        "decision-1",
        {"assessment": {"action": "BUY", "regime": "trend"}, "opinions": _outcome()["agents"]},
        event_id="decision-assessment-decision-1",
        created_at_ms=1_700_000_000_000,
    )
    database.put_json(
        "paper_decision_settlements",
        "decision-1",
        {"decision_id": "decision-1", "selected_action": "BUY", "realized_action": "BUY", "net_pnl": 4.0, "drawdown_contribution": 0.5, "evidence_class": "verified_market", "verified_market_data": True},
        expected_version=0,
    )
    supervisor = SelfLearningSupervisor(database)
    first = supervisor.run_once(now_ms=1_700_000_001_000)
    second = supervisor.run_once(now_ms=1_700_000_002_000)
    assert first["processed_count"] == 1
    assert second["processed_count"] == 0
    assert second["skipped_count"] == 1
    assert first["execution_authority"] is False
    assert first["automatic_execution_promotion"] is False
