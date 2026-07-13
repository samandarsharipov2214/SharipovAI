from __future__ import annotations

import pytest

from decision_quality import DecisionQualityService
from meta_ai_persistence import MetaAIPersistenceError
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'decision-quality.db'}")
    database.initialize()
    return database


def _payloads() -> list[dict[str, object]]:
    return [
        {
            "name": "Market AI",
            "decision": "BUY",
            "confidence": 82,
            "data_quality": 91,
            "risk": 24,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
        {
            "name": "News AI",
            "decision": "BUY",
            "confidence": 74,
            "data_quality": 86,
            "risk": 31,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
    ]


def test_assessment_is_immutable_and_survives_restart(tmp_path) -> None:
    database = _database(tmp_path)
    service = DecisionQualityService(database)
    first = service.evaluate("decision-1", _payloads(), regime="bull", min_agreement=0.5)
    assert first.action == "BUY"

    changed = [{"name": "Market AI", "decision": "SELL", "confidence": 99}]
    restarted = DecisionQualityService(database)
    second = restarted.evaluate("decision-1", changed, regime="bear")

    assert second == first
    events = database.list_events(
        "decision_quality",
        entity_type="decision_assessment",
        entity_id="decision-1",
        limit=10,
    )
    assert len(events) == 1
    assert events[0]["payload"]["execution_authority"] is False


def test_synthetic_agents_are_rejected_before_consensus(tmp_path) -> None:
    service = DecisionQualityService(_database(tmp_path))
    assessment = service.evaluate(
        "decision-synthetic",
        [
            {
                "name": "Synthetic AI",
                "decision": "BUY",
                "confidence": 100,
                "data_quality": 100,
                "risk": 0,
                "evidence_class": "synthetic_simulation",
                "verified_market_data": False,
            }
        ],
        regime="bull",
    )

    assert assessment.action == "WAIT"
    assert assessment.blocked is True
    assert assessment.rejected_agents == ("Synthetic AI",)


def test_risk_engine_keeps_canonical_veto(tmp_path) -> None:
    service = DecisionQualityService(_database(tmp_path))
    payloads = _payloads() + [
        {
            "name": "Risk Engine",
            "decision": "BLOCK",
            "confidence": 100,
            "evidence_score": 100,
            "risk_score": 95,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        }
    ]
    assessment = service.evaluate("decision-risk-veto", payloads, regime="high_volatility")
    assert assessment.action == "BLOCK"
    assert assessment.blocked is True
    assert "veto" in assessment.reason.lower()


def test_settlement_requires_prior_assessment(tmp_path) -> None:
    service = DecisionQualityService(_database(tmp_path))
    with pytest.raises(MetaAIPersistenceError, match="assessed"):
        service.settle(
            "missing-assessment",
            _payloads(),
            realized_action="BUY",
            regime="bull",
        )


def test_verified_settlement_updates_reputation_once(tmp_path) -> None:
    database = _database(tmp_path)
    service = DecisionQualityService(database)
    service.evaluate("decision-settle", _payloads(), regime="bull", min_agreement=0.5)

    first = service.settle(
        "decision-settle",
        _payloads(),
        realized_action="BUY",
        pnl_by_agent={"Market AI": 1.5, "News AI": 1.0},
        regime="bull",
        evidence_class="verified_market",
        verified_market_data=True,
    )
    second = service.settle(
        "decision-settle",
        _payloads(),
        realized_action="SELL",
        pnl_by_agent={"Market AI": 100.0, "News AI": 100.0},
        regime="bull",
        evidence_class="verified_market",
        verified_market_data=True,
    )

    assert first.reputation_recorded is True
    assert second.reputation_recorded is False
    assert second.selected_action == first.selected_action
    assert second.winning_agents == first.winning_agents

    snapshot = DecisionQualityService(database).meta.reputations_snapshot("bull")
    assert snapshot["Market AI"]["total_predictions"] == 1
    assert snapshot["Market AI"]["pnl_contribution"] == 1.5
    assert snapshot["News AI"]["total_predictions"] == 1


def test_synthetic_settlement_cannot_train_reputation(tmp_path) -> None:
    service = DecisionQualityService(_database(tmp_path))
    service.evaluate("decision-no-train", _payloads(), regime="bull", min_agreement=0.5)

    with pytest.raises(MetaAIPersistenceError, match="verified market evidence"):
        service.settle(
            "decision-no-train",
            _payloads(),
            realized_action="BUY",
            regime="bull",
            evidence_class="synthetic_simulation",
            verified_market_data=False,
        )
    snapshot = service.meta.reputations_snapshot()
    assert snapshot
    assert all(row["total_predictions"] == 0 for row in snapshot.values())
    assert all(row["pnl_contribution"] == 0.0 for row in snapshot.values())
