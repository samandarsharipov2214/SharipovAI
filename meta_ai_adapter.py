"""Compatibility adapter between existing SharipovAI agent payloads and MetaAI."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from meta_ai import AgentOpinion, ConsensusResult, MetaAI, PredictionOutcome


def opinions_from_payloads(payloads: Sequence[Mapping[str, Any]], *, regime: str = "unknown") -> list[AgentOpinion]:
    opinions: list[AgentOpinion] = []
    for index, payload in enumerate(payloads):
        agent_id = str(payload.get("agent_id") or payload.get("name") or f"agent-{index}")
        action = str(payload.get("action") or payload.get("decision") or "WAIT").upper()
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        evidence_score = float(payload.get("evidence_score", payload.get("data_quality", 0.5)) or 0.0)
        risk_score = float(payload.get("risk_score", payload.get("risk", 0.5)) or 0.0)
        rationale = str(payload.get("rationale") or payload.get("reason") or "")
        opinions.append(AgentOpinion(agent_id, action, confidence, evidence_score, risk_score, regime, rationale))
    return opinions


def evaluate_agent_payloads(
    meta: MetaAI,
    payloads: Sequence[Mapping[str, Any]],
    *,
    regime: str = "unknown",
    min_evidence: float = 0.35,
    max_risk: float = 0.80,
    min_agreement: float = 0.55,
) -> ConsensusResult:
    return meta.dynamic_consensus(
        opinions_from_payloads(payloads, regime=regime),
        regime=regime,
        min_evidence=min_evidence,
        max_risk=max_risk,
        min_agreement=min_agreement,
    )


def record_realized_result(
    meta: MetaAI,
    payloads: Sequence[Mapping[str, Any]],
    *,
    realized_action: str,
    pnl_by_agent: Mapping[str, float] | None = None,
    drawdown_by_agent: Mapping[str, float] | None = None,
    regime: str = "unknown",
) -> None:
    pnl = pnl_by_agent or {}
    drawdown = drawdown_by_agent or {}
    outcomes = [
        PredictionOutcome(
            agent_id=opinion.agent_id,
            predicted_action=opinion.action,
            realized_action=realized_action,
            confidence=opinion.confidence,
            pnl_contribution=float(pnl.get(opinion.agent_id, 0.0)),
            drawdown_contribution=float(drawdown.get(opinion.agent_id, 0.0)),
            regime=regime,
        )
        for opinion in opinions_from_payloads(payloads, regime=regime)
    ]
    meta.record_outcomes(outcomes)
