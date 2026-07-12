"""Compatibility adapter between existing SharipovAI agent payloads and MetaAI."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from meta_ai import AgentOpinion, ConsensusResult, MetaAI, PredictionOutcome


def opinions_from_payloads(payloads: Sequence[Mapping[str, Any]], *, regime: str = "unknown") -> list[AgentOpinion]:
    """Convert legacy payloads while normalizing 0..1 and 0..100 score scales."""

    opinions: list[AgentOpinion] = []
    for index, payload in enumerate(payloads):
        agent_id = str(payload.get("agent_id") or payload.get("name") or f"agent-{index}")
        action = str(payload.get("action") or payload.get("decision") or "WAIT").upper()
        confidence = _ratio(payload.get("confidence", 0.0), "confidence")
        evidence_score = _ratio(
            payload.get("evidence_score", payload.get("data_quality", 0.5)),
            "evidence_score",
        )
        risk_score = _ratio(
            payload.get("risk_score", payload.get("risk", 0.5)),
            "risk_score",
        )
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
        min_evidence=_ratio(min_evidence, "min_evidence"),
        max_risk=_ratio(max_risk, "max_risk"),
        min_agreement=_ratio(min_agreement, "min_agreement"),
    )


def record_realized_result(
    meta: MetaAI,
    payloads: Sequence[Mapping[str, Any]],
    *,
    realized_action: str,
    pnl_by_agent: Mapping[str, float] | None = None,
    drawdown_by_agent: Mapping[str, float] | None = None,
    regime: str = "unknown",
    decision_id: str | None = None,
    evidence_class: str = "verified_market",
    verified_market_data: bool = True,
) -> bool:
    """Record one realized result in memory or canonical persistent MetaAI.

    Persistent MetaAI instances require ``decision_id`` and verified evidence.
    Plain MetaAI remains backward compatible and records the same outcomes in
    process memory.
    """

    pnl = pnl_by_agent or {}
    drawdown = drawdown_by_agent or {}
    eligible_payloads = [payload for payload in payloads if _learning_eligible(payload)]
    outcomes = [
        PredictionOutcome(
            agent_id=opinion.agent_id,
            predicted_action=opinion.action,
            realized_action=realized_action,
            confidence=opinion.confidence,
            pnl_contribution=_finite(pnl.get(opinion.agent_id, 0.0), "pnl_contribution"),
            drawdown_contribution=_finite(drawdown.get(opinion.agent_id, 0.0), "drawdown_contribution"),
            regime=regime,
        )
        for opinion in opinions_from_payloads(eligible_payloads, regime=regime)
    ]
    if not outcomes:
        return False

    if hasattr(meta, "persistence_status"):
        return bool(
            meta.record_outcomes(
                outcomes,
                decision_id=decision_id,
                evidence_class=evidence_class,
                verified_market_data=verified_market_data,
            )
        )

    meta.record_outcomes(outcomes)
    return True


def _learning_eligible(payload: Mapping[str, Any]) -> bool:
    for field in ("learning_eligible", "evidence_eligible", "reputation_eligible"):
        if payload.get(field) is False:
            return False
    return str(payload.get("evidence_class") or "").strip().lower() not in {
        "synthetic",
        "synthetic_simulation",
        "demo",
        "fixture",
        "mock",
    }


def _ratio(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if 0.0 <= parsed <= 1.0:
        return parsed
    if 1.0 < parsed <= 100.0:
        return parsed / 100.0
    raise ValueError(f"{name} must be within 0..1 or 0..100")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be a finite number")
    return parsed


__all__ = ["evaluate_agent_payloads", "opinions_from_payloads", "record_realized_result"]
