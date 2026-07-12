from __future__ import annotations

import pytest

from meta_ai import AgentOpinion, MetaAI
from meta_ai_adapter import evaluate_agent_payloads, opinions_from_payloads, record_realized_result


def test_adapter_normalizes_percent_and_ratio_scales() -> None:
    opinions = opinions_from_payloads([
        {
            "agent_id": "market_intelligence",
            "action": "BUY",
            "confidence": 80,
            "data_quality": 90,
            "risk": 25,
        }
    ])

    assert len(opinions) == 1
    assert opinions[0].confidence == pytest.approx(0.80)
    assert opinions[0].evidence_score == pytest.approx(0.90)
    assert opinions[0].risk_score == pytest.approx(0.25)


def test_adapter_rejects_scores_outside_supported_scales() -> None:
    with pytest.raises(ValueError, match="confidence"):
        opinions_from_payloads([
            {"agent_id": "market_intelligence", "action": "BUY", "confidence": 101}
        ])


def test_non_authoritative_block_is_suppressed_not_global_veto() -> None:
    result = MetaAI().dynamic_consensus(
        [
            AgentOpinion("market_intelligence", "BUY", 0.85, 0.90, 0.20),
            AgentOpinion("news_intelligence", "BUY", 0.75, 0.80, 0.25),
            AgentOpinion("experimental_agent", "BLOCK", 0.95, 0.10, 0.95),
        ],
        min_agreement=0.50,
    )

    assert result.action == "BUY"
    assert result.blocked is False
    assert "experimental_agent" in result.dissenting_agents
    assert "excluded" in result.reason


def test_risk_and_security_keep_unconditional_veto() -> None:
    risk_result = MetaAI().dynamic_consensus(
        [
            AgentOpinion("market_intelligence", "BUY", 0.90, 0.95, 0.10),
            AgentOpinion("risk_engine", "BLOCK", 1.0, 1.0, 1.0),
        ]
    )
    security_result = MetaAI().dynamic_consensus(
        [
            AgentOpinion("market_intelligence", "BUY", 0.90, 0.95, 0.10),
            AgentOpinion("security_guard", "WAIT", 0.80, 0.90, 0.95),
        ]
    )

    assert risk_result.action == "BLOCK" and risk_result.blocked is True
    assert security_result.action == "BLOCK" and security_result.blocked is True


def test_evaluate_accepts_percentage_thresholds() -> None:
    result = evaluate_agent_payloads(
        MetaAI(),
        [
            {"agent_id": "market_intelligence", "action": "BUY", "confidence": 85, "evidence_score": 90, "risk_score": 20},
            {"agent_id": "news_intelligence", "action": "BUY", "confidence": 80, "evidence_score": 80, "risk_score": 30},
        ],
        min_evidence=70,
        max_risk=80,
        min_agreement=55,
    )

    assert result.action == "BUY"
    assert result.blocked is False


def test_synthetic_payload_does_not_change_reputation() -> None:
    meta = MetaAI()
    payloads = [
        {
            "agent_id": "synthetic_simulator",
            "action": "BUY",
            "confidence": 99,
            "evidence_score": 99,
            "risk_score": 1,
            "evidence_class": "synthetic_simulation",
            "learning_eligible": False,
        },
        {
            "agent_id": "market_intelligence",
            "action": "BUY",
            "confidence": 80,
            "evidence_score": 90,
            "risk_score": 20,
        },
    ]

    record_realized_result(meta, payloads, realized_action="BUY", regime="bull")
    snapshot = meta.reputations_snapshot("bull")

    assert "synthetic_simulator" not in snapshot
    assert snapshot["market_intelligence"]["total_predictions"] == 1
