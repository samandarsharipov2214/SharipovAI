"""Independent General Controller V2 paper-decision evaluation.

This module intentionally separates directional specialist evidence from
non-directional Risk, Portfolio, Security and Decision Quality roles.  It has no
execution authority and performs no I/O; callers must provide explicit gates and
persist/execute only through the canonical paper runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from meta_ai_adapter import opinions_from_payloads

from .general_controller_v2 import (
    DecisionQualitySignal,
    GateSignal,
    GeneralControllerDecision,
    GeneralControllerV2,
    SpecialistRecommendation,
    TradingIntent,
)

_NON_DIRECTIONAL_AGENTS = frozenset(
    {
        "decision_quality",
        "portfolio_engine",
        "risk_engine",
        "security_guard",
    }
)


@dataclass(frozen=True, slots=True)
class ControllerEvaluationV2:
    controller: GeneralControllerDecision
    quality: DecisionQualitySignal
    recommendations: tuple[SpecialistRecommendation, ...]
    execution_authority: bool = False


def recommendations_from_payloads(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[SpecialistRecommendation, ...]:
    """Normalize existing council payloads without granting them authority."""

    opinions = opinions_from_payloads(payloads)
    recommendations: list[SpecialistRecommendation] = []
    for payload, opinion in zip(payloads, opinions, strict=True):
        action = str(opinion.action or "WAIT").upper()
        intent = TradingIntent(action) if action in {"BUY", "SELL", "WAIT"} else TradingIntent.WAIT
        verified = bool(payload.get("verified_market_data") is True or payload.get("data_verified") is True)
        evidence_ids = payload.get("evidence_ids") or payload.get("signal_evidence") or ()
        if isinstance(evidence_ids, str):
            evidence_ids = (evidence_ids,)
        elif not isinstance(evidence_ids, (list, tuple)):
            evidence_ids = ()
        recommendations.append(
            SpecialistRecommendation(
                agent_id=opinion.agent_id,
                intent=intent,
                confidence=_percent(opinion.confidence),
                evidence_score=_percent(opinion.evidence_score),
                risk_score=_percent(opinion.risk_score),
                verified=verified,
                rationale=opinion.rationale,
                evidence_ids=tuple(str(item) for item in evidence_ids if str(item).strip()),
            )
        )
    return tuple(recommendations)


def directional_quality_signal(
    payloads: Sequence[Mapping[str, Any]],
    *,
    freshness_errors: Sequence[str] = (),
) -> DecisionQualitySignal:
    """Measure quality/agreement from directional specialists only.

    Risk, Portfolio, Security and Decision Quality remain gates/advisors. WAIT
    opinions are abstentions rather than directional votes, so they cannot dilute
    BUY/SELL agreement. Missing or stale evidence still fails closed later in the
    General Controller thresholds/gates.
    """

    freshness = tuple(str(item).strip() for item in freshness_errors if str(item).strip())
    if freshness:
        return DecisionQualitySignal(
            blocked=True,
            quality_score=0.0,
            agreement=0.0,
            reason="canonical candidate freshness validation failed: " + "; ".join(freshness),
        )

    rows = [
        item
        for item in recommendations_from_payloads(payloads)
        if item.verified
        and item.agent_id.strip() not in _NON_DIRECTIONAL_AGENTS
        and item.intent in {TradingIntent.BUY, TradingIntent.SELL}
    ]
    if not rows:
        return DecisionQualitySignal(
            blocked=False,
            quality_score=0.0,
            agreement=0.0,
            reason="no verified directional specialist evidence",
        )

    strengths: list[tuple[TradingIntent, float]] = []
    quality_rows: list[float] = []
    for item in rows:
        confidence = item.confidence / 100.0
        evidence = item.evidence_score / 100.0
        residual_risk = max(0.0, 1.0 - item.risk_score / 100.0)
        strength = confidence * evidence * residual_risk
        strengths.append((item.intent, strength))
        quality_rows.append(
            0.45 * confidence
            + 0.40 * evidence
            + 0.15 * residual_risk
        )

    buy = sum(value for intent, value in strengths if intent is TradingIntent.BUY)
    sell = sum(value for intent, value in strengths if intent is TradingIntent.SELL)
    total = buy + sell
    agreement = 0.0 if total <= 0.0 else 100.0 * max(buy, sell) / total
    quality_score = 100.0 * sum(quality_rows) / len(quality_rows)
    return DecisionQualitySignal(
        blocked=False,
        quality_score=min(max(quality_score, 0.0), 100.0),
        agreement=min(max(agreement, 0.0), 100.0),
        reason="directional-only Decision Quality; non-directional gates excluded from direction",
    )


def evaluate_controller_v2(
    payloads: Sequence[Mapping[str, Any]],
    *,
    gates: Sequence[GateSignal],
    freshness_errors: Sequence[str] = (),
    controller: GeneralControllerV2 | None = None,
) -> ControllerEvaluationV2:
    recommendations = recommendations_from_payloads(payloads)
    quality = directional_quality_signal(payloads, freshness_errors=freshness_errors)
    decision = (controller or GeneralControllerV2()).decide(
        recommendations,
        decision_quality=quality,
        gates=gates,
    )
    return ControllerEvaluationV2(
        controller=decision,
        quality=quality,
        recommendations=recommendations,
        execution_authority=False,
    )


def _percent(value: Any) -> float:
    parsed = float(value)
    if 0.0 <= parsed <= 1.0:
        return parsed * 100.0
    if 0.0 <= parsed <= 100.0:
        return parsed
    raise ValueError("percentage signal must be within 0..1 or 0..100")


__all__ = [
    "ControllerEvaluationV2",
    "directional_quality_signal",
    "evaluate_controller_v2",
    "recommendations_from_payloads",
]
