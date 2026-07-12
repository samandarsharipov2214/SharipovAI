"""Canonical paper-decision runtime for SharipovAI.

This module connects existing architectural owners without creating another AI:
Decision Quality -> General Controller directive -> TradingCandidate validation.
It never executes orders. Paper execution may consume only an authorized result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from decision_quality import (
    CandidateBuildResult,
    CandidateEvidencePacket,
    DecisionCandidateBridge,
    DecisionQualityAssessment,
    DecisionQualityService,
)
from storage import ProjectDatabase
from trading_candidate import TradingDecision, TradingEnvironment


class CanonicalPaperRuntimeError(RuntimeError):
    """Raised when the canonical paper decision packet is unsafe."""


@dataclass(frozen=True, slots=True)
class PaperDecisionAuthorization:
    decision_id: str
    authorized: bool
    decision: TradingDecision
    reason: str
    assessment: DecisionQualityAssessment
    candidate_result: CandidateBuildResult
    execution_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "authorized": self.authorized,
            "decision": self.decision.value,
            "reason": self.reason,
            "assessment": self.assessment.to_dict(),
            "candidate": self.candidate_result.candidate.to_dict(),
            "validation": {
                "valid": self.candidate_result.validation.valid,
                "errors": list(self.candidate_result.validation.errors),
            },
            "downgrade_reasons": list(self.candidate_result.downgrade_reasons),
            "execution_authority": False,
        }


class CanonicalPaperDecisionRuntime:
    """Single fail-closed gateway for new autonomous paper entries.

    The runtime coordinates existing services only. It cannot place, size, amend,
    or cancel an order. A separate virtual execution owner may act only when the
    returned authorization is explicitly true.
    """

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        quality: DecisionQualityService | None = None,
        bridge: DecisionCandidateBridge | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.quality = quality or DecisionQualityService(self.database)
        self.bridge = bridge or DecisionCandidateBridge(self.database)
        if self.quality.database.dsn != self.database.dsn:
            raise ValueError("Decision Quality and canonical paper runtime must use the same database")
        if self.bridge.database.dsn != self.database.dsn:
            raise ValueError("Candidate bridge and canonical paper runtime must use the same database")

    def assess_entry(
        self,
        decision_id: str,
        agent_payloads: Sequence[Mapping[str, Any]],
        packet: CandidateEvidencePacket,
        *,
        general_controller_decision: TradingDecision,
        now_ms: int,
        regime: str = "unknown",
        min_evidence: float = 0.35,
        max_risk: float = 0.80,
        min_agreement: float = 0.55,
        min_confidence: float = 70.0,
        min_consensus: float = 70.0,
    ) -> PaperDecisionAuthorization:
        clean_id = str(decision_id or "").strip()
        if not clean_id:
            raise CanonicalPaperRuntimeError("decision_id is required")
        if packet.candidate_id != clean_id:
            raise CanonicalPaperRuntimeError("candidate_id must equal decision_id")
        if packet.environment is not TradingEnvironment.PAPER:
            raise CanonicalPaperRuntimeError("canonical paper runtime accepts PAPER candidates only")
        if not agent_payloads:
            raise CanonicalPaperRuntimeError("at least one independent agent payload is required")

        assessment = self.quality.evaluate(
            clean_id,
            agent_payloads,
            regime=regime,
            min_evidence=min_evidence,
            max_risk=max_risk,
            min_agreement=min_agreement,
        )
        candidate_result = self.bridge.build_and_store(
            assessment,
            packet,
            general_controller_decision=general_controller_decision,
            now_ms=now_ms,
            min_confidence=min_confidence,
            min_consensus=min_consensus,
        )
        decision = candidate_result.candidate.decision
        authorized = bool(
            candidate_result.validation.valid
            and decision is TradingDecision.ALLOW
            and not assessment.blocked
        )
        reason = _authorization_reason(authorized, decision, assessment, candidate_result)
        return PaperDecisionAuthorization(
            decision_id=clean_id,
            authorized=authorized,
            decision=decision,
            reason=reason,
            assessment=assessment,
            candidate_result=candidate_result,
        )

    def status(self) -> dict[str, object]:
        return {
            "owner": "virtual_execution.paper_decision_gateway",
            "decision_owner": "decision_quality",
            "candidate_owner": "general_controller_to_trading_candidate_bridge",
            "execution_authority": False,
            "accepted_environment": TradingEnvironment.PAPER.value,
            "database": self.database.health(),
            "decision_quality": self.quality.status(),
        }


def _authorization_reason(
    authorized: bool,
    decision: TradingDecision,
    assessment: DecisionQualityAssessment,
    result: CandidateBuildResult,
) -> str:
    if authorized:
        return "verified council assessment and canonical TradingCandidate allow paper entry"
    reasons = list(result.downgrade_reasons)
    reasons.extend(result.validation.errors)
    if assessment.reason:
        reasons.append(assessment.reason)
    unique: list[str] = []
    for item in reasons:
        clean = str(item).strip()
        if clean and clean not in unique:
            unique.append(clean)
    detail = "; ".join(unique[:8]) or "canonical decision did not authorize entry"
    return f"{decision.value}: {detail}"


__all__ = [
    "CanonicalPaperDecisionRuntime",
    "CanonicalPaperRuntimeError",
    "PaperDecisionAuthorization",
]
