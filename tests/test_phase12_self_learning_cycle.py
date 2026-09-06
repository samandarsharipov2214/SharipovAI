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
            {"agent_id": "market-agent", "action": "BUY", "confidence": 80.0, "evidence_score": 0.9, "evidence_class": "verified_market", "verified_market_data": True},
            {"agent_id": "risk-agent", "action": "BUY", "confidence": 60.0, "evidence_score": 0.8, "evidence_class": "verified_market", "verified_market_data": True},
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


def test_outcome_replay_repairs_missing_agent_projection_without_double_count(tmp_path) -> None:
    database = _database(tmp_path)
    service = OutcomeAttributionService(database)
    service.record(_outcome())
    metric = database.get_json("self_learning_agent_metrics", "market-agent")
    assert metric is not None
    database.put_json(
        "self_learning_agent_metrics",
        "market-agent",
        {
            "agent_id": "market-agent",
            "outcome_count": 0,
            "correct_count": 0,
            "confidence_error_sum": 0.0,
            "attributed_pnl": 0.0,
            "attributed_drawdown": 0.0,
            "regimes": {},
            "sources": {},
            "applied_outcomes": [],
        },
        expected_version=int(metric["version"]),
    )
    service.record(_outcome())
    repaired = database.get_json("self_learning_agent_metrics", "market-agent")
    assert repaired is not None
    assert repaired["value"]["outcome_count"] == 1
    assert repaired["value"]["applied_outcomes"] == ["outcome-1"]
    service.record(_outcome())
    stable = database.get_json("self_learning_agent_metrics", "market-agent")
    assert stable is not None
    assert stable["value"]["outcome_count"] == 1


def test_policy_rejects_synthetic_and_non_finite_evidence() -> None:
    synthetic = _outcome()
    synthetic["evidence_class"] = "synthetic"
    with pytest.raises(ValueError, match="synthetic"):
        OutcomeEvidence.from_mapping(synthetic)
    invalid = _outcome()
    invalid["net_pnl"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        OutcomeEvidence.from_mapping(invalid)


def test_policy_rejects_unverified_agent_inside_verified_outcome() -> None:
    invalid = _outcome()
    invalid["agents"] = [dict(invalid["agents"][0])]
    invalid["agents"][0].pop("verified_market_data")
    with pytest.raises(ValueError, match="unverified market evidence"):
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


def _stripped_council_opinions() -> list[dict[str, object]]:
    """Production-shaped assessment opinions: organ id present, attestation stripped."""
    return [
        {
            "agent_id": "market_intelligence",
            "action": "BUY",
            "confidence": 0.84,
            "evidence_score": 0.9,
            "risk_score": 0.2,
            "regime": "trend",
            "rationale": "verified council opinion",
        },
        {
            "agent_id": "risk_intelligence",
            "action": "BUY",
            "confidence": 0.7,
            "evidence_score": 0.8,
            "risk_score": 0.25,
            "regime": "trend",
            "rationale": "verified council opinion",
        },
    ]


def test_supervisor_normalizes_stripped_verified_council_opinions(tmp_path) -> None:
    database = _database(tmp_path)
    database.append_event(
        EVENT_NAMESPACE,
        "decision_assessment",
        "decision-f18",
        {"assessment": {"action": "BUY", "regime": "trend"}, "opinions": _stripped_council_opinions()},
        event_id="decision-assessment-decision-f18",
        created_at_ms=1_700_000_000_000,
    )
    database.put_json(
        "paper_decision_settlements",
        "decision-f18",
        {
            "decision_id": "decision-f18",
            "selected_action": "BUY",
            "realized_action": "BUY",
            "net_pnl": 3.5,
            "drawdown_contribution": 0.25,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
        expected_version=0,
    )
    supervisor = SelfLearningSupervisor(database)
    result = supervisor.run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 1
    assert result["failed_count"] == 0
    assert result["execution_authority"] is False
    recorded = database.get_json("self_learning_outcomes", "paper:decision-f18")
    assert recorded is not None
    assert recorded["value"]["evidence_class"] == "verified_market"
    assert recorded["value"]["verified_market_data"] is True
    attribution_ids = {item["agent_id"] for item in recorded["value"]["attributions"]}
    assert attribution_ids == {"market_intelligence", "risk_intelligence"}
    market = database.get_json("self_learning_agent_metrics", "market_intelligence")
    assert market is not None
    assert market["value"]["outcome_count"] == 1


def test_supervisor_rejects_synthetic_agent_class_even_with_verified_settlement(tmp_path) -> None:
    database = _database(tmp_path)
    opinions = _stripped_council_opinions()
    opinions[0]["evidence_class"] = "synthetic"
    opinions[0]["verified_market_data"] = True
    database.append_event(
        EVENT_NAMESPACE,
        "decision_assessment",
        "decision-synthetic",
        {"assessment": {"action": "BUY", "regime": "trend"}, "opinions": opinions},
        event_id="decision-assessment-decision-synthetic",
        created_at_ms=1_700_000_000_000,
    )
    database.put_json(
        "paper_decision_settlements",
        "decision-synthetic",
        {
            "decision_id": "decision-synthetic",
            "selected_action": "BUY",
            "realized_action": "BUY",
            "net_pnl": 1.0,
            "drawdown_contribution": 0.1,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
        expected_version=0,
    )
    result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 0
    assert result["failed_count"] == 1
    assert any("synthetic" in error for error in result["errors"])


def test_supervisor_rejects_unverified_settlement_market_data(tmp_path) -> None:
    database = _database(tmp_path)
    database.append_event(
        EVENT_NAMESPACE,
        "decision_assessment",
        "decision-unverified",
        {"assessment": {"action": "BUY", "regime": "trend"}, "opinions": _stripped_council_opinions()},
        event_id="decision-assessment-decision-unverified",
        created_at_ms=1_700_000_000_000,
    )
    database.put_json(
        "paper_decision_settlements",
        "decision-unverified",
        {
            "decision_id": "decision-unverified",
            "selected_action": "BUY",
            "realized_action": "BUY",
            "net_pnl": 1.0,
            "drawdown_contribution": 0.1,
            "evidence_class": "verified_market",
            "verified_market_data": False,
        },
        expected_version=0,
    )
    result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 0
    assert result["failed_count"] == 1
    assert any("verified market evidence" in error or "verified evidence class" in error for error in result["errors"])


def test_supervisor_rejects_missing_assessment_opinions(tmp_path) -> None:
    database = _database(tmp_path)
    database.append_event(
        EVENT_NAMESPACE,
        "decision_assessment",
        "decision-empty",
        {"assessment": {"action": "BUY", "regime": "trend"}, "opinions": []},
        event_id="decision-assessment-decision-empty",
        created_at_ms=1_700_000_000_000,
    )
    database.put_json(
        "paper_decision_settlements",
        "decision-empty",
        {
            "decision_id": "decision-empty",
            "selected_action": "BUY",
            "realized_action": "BUY",
            "net_pnl": 1.0,
            "drawdown_contribution": 0.1,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
        expected_version=0,
    )
    result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 0
    assert result["failed_count"] == 1
    assert any("opinions are missing" in error for error in result["errors"])

def _put_settlement_with_stripped_opinions(
    database: ProjectDatabase,
    *,
    decision_id: str,
    settlement_fields: dict[str, object],
) -> None:
    database.append_event(
        EVENT_NAMESPACE,
        "decision_assessment",
        decision_id,
        {"assessment": {"action": "BUY", "regime": "trend"}, "opinions": _stripped_council_opinions()},
        event_id=f"decision-assessment-{decision_id}",
        created_at_ms=1_700_000_000_000,
    )
    payload = {
        "decision_id": decision_id,
        "selected_action": "BUY",
        "realized_action": "BUY",
        "net_pnl": 2.0,
        "drawdown_contribution": 0.2,
        **settlement_fields,
    }
    database.put_json(
        "paper_decision_settlements",
        decision_id,
        payload,
        expected_version=0,
    )


def test_supervisor_rejects_missing_settlement_evidence_class(tmp_path) -> None:
    database = _database(tmp_path)
    _put_settlement_with_stripped_opinions(
        database,
        decision_id="decision-missing-class",
        settlement_fields={"verified_market_data": True},
    )
    result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 0
    assert result["failed_count"] == 1
    assert any("evidence_class is required" in error for error in result["errors"])


def test_supervisor_rejects_unsupported_settlement_evidence_class(tmp_path) -> None:
    database = _database(tmp_path)
    _put_settlement_with_stripped_opinions(
        database,
        decision_id="decision-unsupported-class",
        settlement_fields={"evidence_class": "heuristic_guess", "verified_market_data": True},
    )
    result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 0
    assert result["failed_count"] == 1
    assert any("unsupported settlement evidence_class" in error for error in result["errors"])


def test_supervisor_processes_explicit_verified_exchange_class(tmp_path) -> None:
    database = _database(tmp_path)
    _put_settlement_with_stripped_opinions(
        database,
        decision_id="decision-verified-exchange",
        settlement_fields={"evidence_class": "verified_exchange", "verified_market_data": True},
    )
    result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
    assert result["processed_count"] == 1
    assert result["failed_count"] == 0
    recorded = database.get_json("self_learning_outcomes", "paper:decision-verified-exchange")
    assert recorded is not None
    assert recorded["value"]["evidence_class"] == "verified_exchange"
    assert recorded["value"]["verified_market_data"] is True


def test_supervisor_rejects_forbidden_settlement_evidence_classes(tmp_path) -> None:
    for forbidden in ("synthetic", "demo", "mock", "fixture", "simulation"):
        case_dir = tmp_path / forbidden
        case_dir.mkdir()
        database = _database(case_dir)
        _put_settlement_with_stripped_opinions(
            database,
            decision_id=f"decision-{forbidden}",
            settlement_fields={"evidence_class": forbidden, "verified_market_data": True},
        )
        result = SelfLearningSupervisor(database).run_once(now_ms=1_700_000_001_000)
        assert result["processed_count"] == 0, forbidden
        assert result["failed_count"] == 1, forbidden
        assert any("synthetic" in error or forbidden in error for error in result["errors"]), forbidden

