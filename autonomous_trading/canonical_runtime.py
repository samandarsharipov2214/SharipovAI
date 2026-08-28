"""Canonical paper-decision runtime for SharipovAI Architecture V2.

Decision Quality is advisory/quality-only. General Controller V2 owns the final
BUY/SELL/WAIT direction, Risk/Security remain veto gates, Portfolio remains a
non-directional solvency/size gate, and TradingCandidate validation is the final
fail-closed structural boundary before virtual execution may consume an ALLOW.

This module never places real orders and accepts PAPER candidates only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
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
from trading_candidate import TradingDecision, TradingEnvironment, TradingSide

from .general_controller_v2 import TradingIntent
from .runtime_decision_v2 import ControllerEvaluationV2, evaluate_controller_v2
from .runtime_gate_provider_v2 import CanonicalShadowGateProvider


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
    v2_decision_namespace = "paper_v2_decisions"

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
        self.v2_gates = CanonicalShadowGateProvider(self.database)
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
        """Assess one PAPER entry with GC V2 as the final directional owner.

        ``general_controller_decision`` is retained only as legacy migration
        evidence. It cannot authorize or block the V2 paper path.
        """

        clean_id = _decision_id(decision_id)
        if self.database.get_json(self.consumption_namespace, clean_id) is not None:
            raise CanonicalPaperRuntimeError("paper authorization has already been consumed")
        if packet.candidate_id != clean_id:
            raise CanonicalPaperRuntimeError("candidate_id must equal decision_id")
        if packet.environment is not TradingEnvironment.PAPER:
            raise CanonicalPaperRuntimeError("canonical paper runtime accepts PAPER candidates only")
        if not agent_payloads:
            raise CanonicalPaperRuntimeError("at least one independent agent payload is required")

        # Keep legacy Decision Quality persistence for audit/reputation history,
        # but it is no longer allowed to own BUY/SELL direction.
        legacy_assessment = self.quality.evaluate(
            clean_id,
            agent_payloads,
            regime=regime,
            min_evidence=min_evidence,
            max_risk=max_risk,
            min_agreement=min_agreement,
        )

        gates = self.v2_gates.pre_decision(packet)
        evaluated = evaluate_controller_v2(
            agent_payloads,
            gates=gates,
            freshness_errors=_packet_freshness_errors(packet, now_ms=now_ms),
        )
        controller = evaluated.controller
        effective_packet, bridge_decision = _controller_candidate_packet(packet, controller.final_intent)
        effective_assessment = _effective_v2_assessment(
            legacy_assessment,
            evaluated,
        )

        candidate_result = self.bridge.build_and_store(
            effective_assessment,
            effective_packet,
            general_controller_decision=bridge_decision,
            now_ms=now_ms,
            min_confidence=min_confidence,
            min_consensus=min_consensus,
        )
        decision = candidate_result.candidate.decision
        authorized = bool(
            candidate_result.validation.valid
            and decision is TradingDecision.ALLOW
            and not effective_assessment.blocked
            and controller.final_intent in {TradingIntent.BUY, TradingIntent.SELL}
        )
        reason = _authorization_reason(authorized, decision, effective_assessment, candidate_result)
        self._persist_v2_decision(
            decision_id=clean_id,
            packet=packet,
            effective_packet=effective_packet,
            legacy_controller_decision=general_controller_decision,
            legacy_assessment=legacy_assessment,
            evaluated=evaluated,
            gates=gates,
            candidate_result=candidate_result,
            authorized=authorized,
            now_ms=now_ms,
        )
        return PaperDecisionAuthorization(
            decision_id=clean_id,
            authorized=authorized,
            decision=decision,
            reason=reason,
            assessment=effective_assessment,
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
        return self._consume_once(
            decision_id=authorization.decision_id,
            candidate_id=candidate.candidate_id,
            environment=candidate.environment.value,
            decision=candidate.decision.value,
            consumed_at_ms=consumed_at_ms,
        )

    def recover_staged_authorization(
        self,
        decision_id: str,
        candidate_id: str,
        *,
        consumed_at_ms: int,
    ) -> dict[str, Any]:
        """Consume a durably staged authorization after a crash or transient DB failure."""

        clean_id = _decision_id(decision_id)
        clean_candidate = _decision_id(candidate_id)
        if clean_candidate != clean_id:
            raise CanonicalPaperRuntimeError("staged authorization candidate identity mismatch")
        decision_record = self.database.get_json(self.v2_decision_namespace, clean_id)
        decision_value = decision_record.get("value") if decision_record else None
        if not isinstance(decision_value, Mapping):
            raise CanonicalPaperRuntimeError("durable V2 decision is unavailable")
        controller = decision_value.get("controller")
        final_intent = (
            str(controller.get("final_intent") or "").upper()
            if isinstance(controller, Mapping)
            else ""
        )
        if (
            decision_value.get("authorized") is not True
            or decision_value.get("candidate_validation_valid") is not True
            or str(decision_value.get("candidate_decision") or "").upper() != "ALLOW"
            or final_intent not in {"BUY", "SELL"}
        ):
            raise CanonicalPaperRuntimeError("durable V2 decision does not authorize PAPER execution")
        candidate_record = self.database.get_json("trading_candidates", clean_candidate)
        candidate = candidate_record.get("value") if candidate_record else None
        if not isinstance(candidate, Mapping):
            raise CanonicalPaperRuntimeError("durable TradingCandidate is unavailable")
        if (
            str(candidate.get("candidate_id") or "") != clean_candidate
            or str(candidate.get("environment") or "").lower() != "paper"
            or str(candidate.get("decision") or "").upper() != "ALLOW"
        ):
            raise CanonicalPaperRuntimeError("durable TradingCandidate is not executable PAPER evidence")
        return self._consume_once(
            decision_id=clean_id,
            candidate_id=clean_candidate,
            environment="paper",
            decision="ALLOW",
            consumed_at_ms=consumed_at_ms,
        )

    def _consume_once(
        self,
        *,
        decision_id: str,
        candidate_id: str,
        environment: str,
        decision: str,
        consumed_at_ms: int,
    ) -> dict[str, Any]:
        if consumed_at_ms <= 0:
            raise CanonicalPaperRuntimeError("consumed_at_ms must be positive")
        payload = {
            "decision_id": decision_id,
            "candidate_id": candidate_id,
            "consumed_at_ms": int(consumed_at_ms),
            "environment": environment,
            "decision": decision,
            "paper_decision_owner": "general_controller_v2",
            "execution_authority": False,
        }
        try:
            self.database.put_json(
                self.consumption_namespace,
                decision_id,
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
        """Settle a paper position without deriving BUY/SELL labels from PnL."""

        clean_id = _decision_id(decision_id)
        existing = self.database.get_json(self.settlement_namespace, clean_id)
        if existing is not None:
            return dict(existing["value"])
        pnl = _finite(net_pnl, "net_pnl")
        drawdown = max(0.0, _finite(drawdown_contribution, "drawdown_contribution"))

        # V2 learning is side/outcome preserving. A loss must never be rewritten
        # as realized SELL (nor a profit as realized BUY), because that corrupts
        # agent reputation. Counterfactual attribution/replay decides later which
        # role, if any, was wrong.
        v2_record = self.database.get_json(self.v2_decision_namespace, clean_id)
        if isinstance(v2_record, Mapping) and isinstance(v2_record.get("value"), Mapping):
            value = v2_record["value"]
            controller = value.get("controller") if isinstance(value.get("controller"), Mapping) else {}
            selected_action = str(controller.get("final_intent") or "WAIT").upper()
            outcome = "PROFIT" if pnl > 1e-9 else "LOSS" if pnl < -1e-9 else "FLAT"
            result = {
                "decision_id": clean_id,
                "selected_action": selected_action,
                "realized_outcome": outcome,
                "reputation_recorded": False,
                "legacy_direction_labeling_disabled": True,
                "learning_mode": "v2_role_aware_pending_replay",
                "net_pnl": pnl,
                "drawdown_contribution": drawdown,
                "evidence_class": "verified_market",
                "verified_market_data": True,
                "execution_authority": False,
            }
            return self._put_settlement_once(clean_id, result)

        # Backward-compatible settlement for positions opened before the V2
        # migration. Losses become HOLD/no-direction instead of rewarding the
        # opposite side. PnL attribution is limited to agents that actually
        # supported the selected direction.
        assessment = self.quality.get_assessment(clean_id)
        if assessment is None:
            raise CanonicalPaperRuntimeError("cannot settle a decision without an assessment")
        payloads = self._stored_opinions(clean_id)
        if not payloads:
            raise CanonicalPaperRuntimeError("stored assessment contains no eligible opinions")
        selected = str(assessment.action or "WAIT").upper()
        implicated = [item for item in payloads if str(item.get("action") or "").upper() == selected]
        if not implicated:
            implicated = [item for item in payloads if str(item.get("action") or "").upper() in {"BUY", "SELL"}]
        divisor = max(1, len(implicated))
        pnl_by_agent = {str(item.get("agent_id")): 0.0 for item in payloads}
        drawdown_by_agent = {str(item.get("agent_id")): 0.0 for item in payloads}
        for item in implicated:
            agent_id = str(item.get("agent_id"))
            pnl_by_agent[agent_id] = pnl / divisor
            drawdown_by_agent[agent_id] = drawdown / divisor
        realized_action = selected if pnl > 1e-9 and selected in {"BUY", "SELL"} else "HOLD"
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
            "legacy_direction_labeling_disabled": True,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        }
        return self._put_settlement_once(clean_id, result)

    def _put_settlement_once(self, decision_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        try:
            self.database.put_json(
                self.settlement_namespace,
                decision_id,
                payload,
                expected_version=0,
            )
        except VersionConflict:
            concurrent = self.database.get_json(self.settlement_namespace, decision_id)
            if concurrent is None:
                raise
            return dict(concurrent["value"])
        return payload

    def _persist_v2_decision(
        self,
        *,
        decision_id: str,
        packet: CandidateEvidencePacket,
        effective_packet: CandidateEvidencePacket,
        legacy_controller_decision: TradingDecision,
        legacy_assessment: DecisionQualityAssessment,
        evaluated: ControllerEvaluationV2,
        gates: Sequence[Any],
        candidate_result: CandidateBuildResult,
        authorized: bool,
        now_ms: int,
    ) -> None:
        payload = {
            "decision_id": decision_id,
            "decided_at_ms": int(now_ms),
            "paper_authority": True,
            "paper_decision_owner": "general_controller_v2",
            "decision_quality_role": "advisory_quality_only",
            "risk_security_role": "veto_only",
            "portfolio_role": "sizing_limits_only",
            "legacy_provider_directive": legacy_controller_decision.value,
            "legacy_provider_directive_authority": False,
            "legacy_decision_quality": legacy_assessment.to_dict(),
            "directional_quality": {
                "blocked": evaluated.quality.blocked,
                "quality_score": evaluated.quality.quality_score,
                "agreement": evaluated.quality.agreement,
                "reason": evaluated.quality.reason,
            },
            "controller": evaluated.controller.to_dict(),
            "gates": [
                {
                    "gate": gate.gate,
                    "verdict": gate.verdict.value,
                    "reasons": list(gate.reasons),
                    "max_notional_usdt": gate.max_notional_usdt,
                }
                for gate in gates
            ],
            "source_packet_side": packet.side.value,
            "candidate_side": effective_packet.side.value,
            "candidate_decision": candidate_result.candidate.decision.value,
            "candidate_validation_valid": candidate_result.validation.valid,
            "candidate_validation_errors": list(candidate_result.validation.errors),
            "authorized": bool(authorized),
            "execution_authority": False,
        }
        existing = self.database.get_json(self.v2_decision_namespace, decision_id)
        if existing is not None:
            if existing.get("value") != payload:
                raise CanonicalPaperRuntimeError("immutable V2 decision collision")
            return
        try:
            self.database.put_json(
                self.v2_decision_namespace,
                decision_id,
                payload,
                expected_version=0,
            )
        except VersionConflict as exc:
            concurrent = self.database.get_json(self.v2_decision_namespace, decision_id)
            if concurrent is None or concurrent.get("value") != payload:
                raise CanonicalPaperRuntimeError("immutable V2 decision collision") from exc

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
            "decision_owner": "general_controller_v2",
            "paper_authority": "general_controller_v2",
            "decision_quality_role": "advisory_quality_only",
            "risk_security_role": "veto_only",
            "portfolio_role": "sizing_limits_only",
            "legacy_provider_directive_authority": False,
            "candidate_owner": "general_controller_v2_to_trading_candidate_bridge",
            "execution_authority": False,
            "accepted_environment": TradingEnvironment.PAPER.value,
            "authorization_single_use": True,
            "side_preserving_exit_learning": True,
            "legacy_pnl_direction_labels_disabled_for_v2": True,
            "database": self.database.health(),
            "decision_quality": self.quality.status(),
        }


def _effective_v2_assessment(
    legacy: DecisionQualityAssessment,
    evaluated: ControllerEvaluationV2,
) -> DecisionQualityAssessment:
    controller = evaluated.controller
    quality = evaluated.quality
    return replace(
        legacy,
        action=controller.final_intent.value,
        confidence=min(max(controller.confidence / 100.0, 0.0), 1.0),
        agreement=min(max(quality.agreement / 100.0, 0.0), 1.0),
        quality_score=min(max(quality.quality_score / 100.0, 0.0), 1.0),
        blocked=bool(controller.blocked),
        reason=controller.reason,
        weighted_scores={
            "BUY": float(controller.buy_score),
            "SELL": float(controller.sell_score),
        },
    )


def _controller_candidate_packet(
    packet: CandidateEvidencePacket,
    intent: TradingIntent,
) -> tuple[CandidateEvidencePacket, TradingDecision]:
    if intent is TradingIntent.BUY:
        return replace(packet, side=TradingSide.BUY), TradingDecision.ALLOW
    if intent is TradingIntent.SELL:
        return replace(packet, side=TradingSide.SELL), TradingDecision.ALLOW
    return packet, TradingDecision.WAIT


def _packet_freshness_errors(packet: CandidateEvidencePacket, *, now_ms: int) -> tuple[str, ...]:
    errors: list[str] = []
    if now_ms <= 0:
        errors.append("now_ms must be positive")
    if packet.market_timestamp_ms <= 0:
        errors.append("market_timestamp_ms must be positive")
    if packet.received_timestamp_ms < packet.market_timestamp_ms:
        errors.append("received_timestamp_ms must not precede market_timestamp_ms")
    if packet.market_timestamp_ms > now_ms + 1_000:
        errors.append("market_timestamp_ms is too far in the future")
    if packet.received_timestamp_ms > now_ms + 1_000:
        errors.append("received_timestamp_ms is too far in the future")
    if packet.expires_at_ms <= now_ms:
        errors.append("candidate is expired")
    if now_ms - packet.market_timestamp_ms > 2_500:
        errors.append("market data is stale")
    return tuple(errors)


def _authorization_reason(
    authorized: bool,
    decision: TradingDecision,
    assessment: DecisionQualityAssessment,
    result: CandidateBuildResult,
) -> str:
    if authorized:
        return "General Controller V2 finalized direction and canonical TradingCandidate allowed PAPER entry"
    reasons = list(result.downgrade_reasons)
    reasons.extend(result.validation.errors)
    if assessment.reason:
        reasons.append(assessment.reason)
    unique: list[str] = []
    for item in reasons:
        clean = str(item).strip()
        if clean and clean not in unique:
            unique.append(clean)
    detail = "; ".join(unique[:8]) or "canonical V2 decision did not authorize paper entry"
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
