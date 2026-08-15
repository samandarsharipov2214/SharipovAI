"""Runtime adapter that observes the authoritative paper path with GC V2.

This module is deliberately non-executing. The existing canonical paper runtime
remains authoritative; the General Controller V2 result is evaluated on the
same immutable evidence packet and recorded only as a shadow comparison.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from meta_ai_adapter import opinions_from_payloads
from trading_candidate import TradingDecision, TradingSide

from .canonical_runtime import PaperDecisionAuthorization
from .general_controller_v2 import (
    DecisionQualitySignal,
    GateSignal,
    GeneralControllerDecision,
    GeneralControllerV2,
    SpecialistRecommendation,
    TradingIntent,
)
from .shadow_dual_run_v2 import (
    Decision,
    PathDecision,
    ShadowComparison,
    ShadowInput,
    compare_shadow,
)


@dataclass(frozen=True, slots=True)
class RuntimeShadowResult:
    comparison: ShadowComparison
    controller: GeneralControllerDecision
    snapshot_id: str
    evidence_hash: str
    execution_authority: bool = False


class RuntimeShadowV2:
    """Evaluate GC V2 beside the current paper authorization without mutation."""

    def __init__(self, controller: GeneralControllerV2 | None = None) -> None:
        self.controller = controller or GeneralControllerV2()

    def evaluate(
        self,
        *,
        authorization: PaperDecisionAuthorization,
        evidence_packet: Any,
        agent_payloads: Sequence[Mapping[str, Any]],
        gates: Sequence[GateSignal],
    ) -> RuntimeShadowResult:
        candidate = authorization.candidate_result.candidate
        if candidate.candidate_id != authorization.decision_id:
            raise ValueError("paper authorization candidate identity mismatch")
        if getattr(evidence_packet, "candidate_id", None) != authorization.decision_id:
            raise ValueError("shadow evidence packet must match authoritative decision_id")
        if getattr(evidence_packet, "market_timestamp_ms", None) != candidate.market_timestamp_ms:
            raise ValueError("shadow and authoritative paths must use the same market timestamp")

        shadow_input = immutable_shadow_input(evidence_packet)
        recommendations = _recommendations(agent_payloads)
        assessment = authorization.assessment
        quality = DecisionQualitySignal(
            blocked=bool(assessment.blocked),
            quality_score=_percent(assessment.quality_score),
            agreement=_percent(assessment.agreement),
            reason=str(assessment.reason or ""),
        )
        controller = self.controller.decide(
            recommendations,
            decision_quality=quality,
            gates=gates,
        )

        authoritative = PathDecision(
            path="canonical_paper_runtime",
            decision=_authoritative_direction(authorization),
            reason=authorization.reason,
            snapshot_id=shadow_input.snapshot_id,
            evidence_hash=shadow_input.evidence_hash,
            execution_authority=True,
        )
        challenger = PathDecision(
            path="general_controller_v2_shadow",
            decision=Decision(controller.final_intent.value),
            reason=controller.reason,
            snapshot_id=shadow_input.snapshot_id,
            evidence_hash=shadow_input.evidence_hash,
            execution_authority=False,
        )
        comparison = compare_shadow(
            shadow_input=shadow_input,
            authoritative=authoritative,
            challenger=challenger,
        )
        return RuntimeShadowResult(
            comparison=comparison,
            controller=controller,
            snapshot_id=shadow_input.snapshot_id,
            evidence_hash=shadow_input.evidence_hash,
            execution_authority=False,
        )


def immutable_shadow_input(evidence_packet: Any) -> ShadowInput:
    """Fingerprint the exact canonical evidence packet consumed by both paths."""

    candidate_id = str(getattr(evidence_packet, "candidate_id", "") or "").strip()
    market_ts_ms = int(getattr(evidence_packet, "market_timestamp_ms", 0) or 0)
    if not candidate_id or market_ts_ms <= 0:
        raise ValueError("canonical evidence packet lacks immutable identity")
    payload = _jsonable(asdict(evidence_packet))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    evidence_hash = hashlib.sha256(encoded).hexdigest()
    return ShadowInput(
        snapshot_id=f"{candidate_id}:{market_ts_ms}",
        evidence_hash=evidence_hash,
        market_ts_ms=market_ts_ms,
    )


def _recommendations(payloads: Sequence[Mapping[str, Any]]) -> tuple[SpecialistRecommendation, ...]:
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


def _authoritative_direction(authorization: PaperDecisionAuthorization) -> Decision:
    if not authorization.authorized or authorization.decision is not TradingDecision.ALLOW:
        return Decision.WAIT
    side = authorization.candidate_result.candidate.side
    if side is TradingSide.BUY:
        return Decision.BUY
    if side is TradingSide.SELL:
        return Decision.SELL
    return Decision.WAIT


def _percent(value: Any) -> float:
    parsed = float(value)
    if 0.0 <= parsed <= 1.0:
        return parsed * 100.0
    if 0.0 <= parsed <= 100.0:
        return parsed
    raise ValueError("percentage signal must be within 0..1 or 0..100")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


__all__ = ["RuntimeShadowResult", "RuntimeShadowV2", "immutable_shadow_input"]
