"""Canonical paper-decision runtime for SharipovAI.

This module connects existing architectural owners without creating another AI:
Decision Quality -> General Controller directive -> TradingCandidate validation.
It never executes orders. Paper execution may consume only an authorized result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from decision_quality import (
    CandidateBuildResult,
    CandidateEvidencePacket,
    DecisionCandidateBridge,
    DecisionQualityAssessment,
    DecisionQualityService,
)
from meta_ai_persistence import EVENT_NAMESPACE
from storage import ProjectDatabase, VersionConflict
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
    """Single fail-closed gateway for autonomous paper entries and learning."""

    consumption_namespace = "paper_authorization_consumption"
    settlement_namespace = "paper_decision_settlements"

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
        clean_id = _decision_id(decision_id)
        if self.database.get_json(self.consumption_namespace, clean_id) is not None:
            raise CanonicalPaperRuntimeError("paper authorization has already been consumed")
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

    def consume_authorization(
        self,
        authorization: PaperDecisionAuthorization,
        *,
        consumed_at_ms: int,
    ) -> dict[str, Any]:
        """Atomically consume an ALLOW once, before virtual execution mutates cash."""

        if authorization.authorized is not True or authorization.decision is not TradingDecision.ALLOW:
            raise CanonicalPaperRuntimeError("only an authorized ALLOW may be consumed")
        if consumed_at_ms <= 0:
            raise CanonicalPaperRuntimeError("consumed_at_ms must be positive")
        candidate = authorization.candidate_result.candidate
        if candidate.candidate_id != authorization.decision_id:
            raise CanonicalPaperRuntimeError("authorization candidate identity mismatch")
        payload = {
            "decision_id": authorization.decision_id,
            "candidate_id": candidate.candidate_id,
            "consumed_at_ms": int(consumed_at_ms),
            "environment": candidate.environment.value,
            "decision": candidate.decision.value,
            "execution_authority": False,
        }
        try:
            self.database.put_json(
                self.consumption_namespace,
                authorization.decision_id,
                payload,
                expected_version=0,
            )
        except VersionConflict as exc:
            raise CanonicalPaperRuntimeError("paper authorization was already consumed") from exc
        return payload

    def settle_exit(
        self,
        decision_id: str,
        *,
        net_pnl: float,
        drawdown_contribution: float,
    ) -> dict[str, Any]:
        """Settle one closed paper position and update reputation exactly once."""

        clean_id = _decision_id(decision_id)
        existing = self.database.get_json(self.settlement_namespace, clean_id)
        if existing is not None:
            return dict(existing["value"])
        pnl = _finite(net_pnl, "net_pnl")
        drawdown = max(0.0, _finite(drawdown_contribution, "drawdown_contribution"))
        assessment = self.quality.get_assessment(clean_id)
        if assessment is None:
            raise CanonicalPaperRuntimeError("cannot settle a decision without an assessment")
        payloads = self._stored_opinions(clean_id)
        if not payloads:
            raise CanonicalPaperRuntimeError("stored assessment contains no eligible opinions")
        allocation = pnl / len(payloads)
        drawdown_allocation = drawdown / len(payloads)
        pnl_by_agent = {str(item.get("agent_id")): allocation for item in payloads}
        drawdown_by_agent = {
            str(item.get("agent_id")): drawdown_allocation for item in payloads
        }
        realized_action = "BUY" if pnl > 1e-9 else "SELL" if pnl < -1e-9 else "HOLD"
        settlement = self.quality.settle(
            clean_id,
            payloads,
            realized_action=realized_action,
            pnl_by_agent=pnl_by_agent,
            drawdown_by_agent=drawdown_by_agent,
            regime=assessment.regime,
            evidence_class="verified_market",
            verified_market_data=True,
        )
        result = {
            **settlement.to_dict(),
            "net_pnl": pnl,
            "drawdown_contribution": drawdown,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        }
        try:
            self.database.put_json(
                self.settlement_namespace,
                clean_id,
                result,
                expected_version=0,
            )
        except VersionConflict:
            concurrent = self.database.get_json(self.settlement_namespace, clean_id)
            if concurrent is None:
                raise
            return dict(concurrent["value"])
        return result

    def _stored_opinions(self, decision_id: str) -> list[dict[str, Any]]:
        events = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="decision_assessment",
            entity_id=decision_id,
            limit=1,
        )
        if not events:
            return []
        payload = events[0].get("payload")
        if not isinstance(payload, Mapping):
            return []
        opinions = payload.get("opinions")
        if not isinstance(opinions, list):
            return []
        result: list[dict[str, Any]] = []
        for item in opinions:
            if not isinstance(item, Mapping):
                continue
            normalized = dict(item)
            normalized.update(
                evidence_class="verified_market",
                verified_market_data=True,
                learning_eligible=True,
                evidence_eligible=True,
                reputation_eligible=True,
            )
            result.append(normalized)
        return result

    def status(self) -> dict[str, object]:
        return {
            "owner": "virtual_execution.paper_decision_gateway",
            "decision_owner": "decision_quality",
            "candidate_owner": "general_controller_to_trading_candidate_bridge",
            "execution_authority": False,
            "accepted_environment": TradingEnvironment.PAPER.value,
            "authorization_single_use": True,
            "verified_exit_settlement": True,
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


def _decision_id(value: Any) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 170:
        raise CanonicalPaperRuntimeError("decision_id is invalid")
    return clean


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CanonicalPaperRuntimeError(f"{field} must be finite")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise CanonicalPaperRuntimeError(f"{field} must be finite")
    return parsed


__all__ = [
    "CanonicalPaperDecisionRuntime",
    "CanonicalPaperRuntimeError",
    "PaperDecisionAuthorization",
]
