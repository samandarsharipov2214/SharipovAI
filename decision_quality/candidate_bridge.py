"""Fail-closed bridge from Decision Quality to canonical TradingCandidate."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from storage import ProjectDatabase, ProjectDomainStore, StoredRecord
from trading_candidate import (
    CandidateValidation,
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
    TrustedSecurityApproval,
    validate_trading_candidate,
)

from .service import DecisionQualityAssessment


class CandidateBridgeError(RuntimeError):
    """Raised when an evidence packet is structurally unsafe."""


@dataclass(frozen=True, slots=True)
class CandidateEvidencePacket:
    candidate_id: str
    symbol: str
    category: TradingCategory
    side: TradingSide
    environment: TradingEnvironment
    market_timestamp_ms: int
    received_timestamp_ms: int
    reference_price: float
    data_sources: tuple[str, ...]
    market_regime: MarketRegime
    signal_evidence: tuple[str, ...]
    news_evidence: tuple[str, ...]
    news_assessment_id: str
    portfolio_snapshot_id: str
    cost_snapshot_id: str
    estimated_fees: float
    estimated_slippage: float
    risk_score: float
    risk_blocks: tuple[str, ...]
    expires_at_ms: int
    security_approval_id: str = ""


@dataclass(frozen=True, slots=True)
class CandidateBuildResult:
    candidate: TradingCandidate
    validation: CandidateValidation
    stored_record: StoredRecord
    general_controller_decision: TradingDecision
    downgrade_reasons: tuple[str, ...]


class DecisionCandidateBridge:
    """Convert an assessed council decision into a validated stored candidate.

    The bridge has no execution authority. It can only preserve or downgrade
    Decision Quality and General Controller decisions.
    """

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        store: ProjectDomainStore | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.store = store or ProjectDomainStore(self.database)
        if self.store.database.dsn != self.database.dsn:
            raise ValueError("DecisionCandidateBridge and ProjectDomainStore must use the same database")

    def build_and_store(
        self,
        assessment: DecisionQualityAssessment,
        packet: CandidateEvidencePacket,
        *,
        general_controller_decision: TradingDecision,
        now_ms: int,
        min_confidence: float = 70.0,
        min_consensus: float = 70.0,
        trusted_security_approvals: Mapping[str, TrustedSecurityApproval] | None = None,
    ) -> CandidateBuildResult:
        if packet.candidate_id != assessment.decision_id:
            raise CandidateBridgeError("candidate_id must equal the immutable decision_id")

        decision, reasons = _effective_decision(
            assessment,
            packet,
            general_controller_decision=general_controller_decision,
            min_confidence=min_confidence,
            min_consensus=min_consensus,
        )
        assessment_evidence_id = f"decision-assessment-{assessment.decision_id}"
        signal_evidence = _unique(packet.signal_evidence + (assessment_evidence_id,))
        risk_blocks = _unique(packet.risk_blocks + tuple(reasons if decision is TradingDecision.BLOCK else ()))

        candidate = TradingCandidate(
            candidate_id=packet.candidate_id,
            symbol=packet.symbol,
            category=packet.category,
            side=packet.side,
            environment=packet.environment,
            market_timestamp_ms=packet.market_timestamp_ms,
            received_timestamp_ms=packet.received_timestamp_ms,
            reference_price=packet.reference_price,
            data_sources=_unique(packet.data_sources),
            market_regime=packet.market_regime,
            signal_evidence=signal_evidence,
            news_evidence=_unique(packet.news_evidence),
            news_assessment_id=packet.news_assessment_id,
            portfolio_snapshot_id=packet.portfolio_snapshot_id,
            cost_snapshot_id=packet.cost_snapshot_id,
            estimated_fees=packet.estimated_fees,
            estimated_slippage=packet.estimated_slippage,
            risk_score=packet.risk_score,
            risk_blocks=risk_blocks,
            confidence=round(assessment.confidence * 100.0, 6),
            consensus=round(assessment.agreement * 100.0, 6),
            decision=decision,
            expires_at_ms=packet.expires_at_ms,
            security_approval_id=packet.security_approval_id,
        )

        validation = validate_trading_candidate(
            candidate,
            now_ms=now_ms,
            min_confidence=min_confidence,
            min_consensus=min_consensus,
            trusted_security_approvals=trusted_security_approvals,
        )
        if not validation.valid:
            original_errors = validation.errors
            blocked = replace(
                candidate,
                decision=TradingDecision.BLOCK,
                risk_blocks=_unique(candidate.risk_blocks + original_errors),
            )
            blocked_validation = validate_trading_candidate(
                blocked,
                now_ms=now_ms,
                min_confidence=min_confidence,
                min_consensus=min_consensus,
                trusted_security_approvals=trusted_security_approvals,
            )
            if not blocked_validation.valid:
                self.store.append_audit(
                    event_type="candidate_bridge_rejected",
                    severity="error",
                    payload={
                        "candidate_id": packet.candidate_id,
                        "decision_id": assessment.decision_id,
                        "errors": list(blocked_validation.errors),
                        "execution_authority": False,
                    },
                    correlation_id=assessment.decision_id,
                )
                raise CandidateBridgeError(
                    "structurally invalid candidate evidence: " + "; ".join(blocked_validation.errors)
                )
            candidate = blocked
            validation = blocked_validation
            reasons.extend(item for item in original_errors if item not in reasons)

        stored = self.store.save_trading_candidate(candidate)
        return CandidateBuildResult(
            candidate=candidate,
            validation=validation,
            stored_record=stored,
            general_controller_decision=general_controller_decision,
            downgrade_reasons=tuple(_unique(tuple(reasons))),
        )


def _effective_decision(
    assessment: DecisionQualityAssessment,
    packet: CandidateEvidencePacket,
    *,
    general_controller_decision: TradingDecision,
    min_confidence: float,
    min_consensus: float,
) -> tuple[TradingDecision, list[str]]:
    action = assessment.action.upper()
    reasons: list[str] = []

    if general_controller_decision is TradingDecision.BLOCK:
        return TradingDecision.BLOCK, ["general_controller_block"]
    if action == "BLOCK":
        return TradingDecision.BLOCK, ["decision_quality_block"]
    if assessment.blocked or action in {"WAIT", "HOLD"}:
        return TradingDecision.WAIT, ["decision_quality_wait"]
    if general_controller_decision is TradingDecision.WAIT:
        return TradingDecision.WAIT, ["general_controller_wait"]
    if action not in {"BUY", "SELL"}:
        return TradingDecision.BLOCK, ["unsupported_decision_quality_action"]

    expected_side = TradingSide.BUY if action == "BUY" else TradingSide.SELL
    if packet.side is not expected_side:
        return TradingDecision.BLOCK, ["decision_side_mismatch"]
    if packet.risk_blocks:
        return TradingDecision.BLOCK, ["risk_engine_blocks_present"]
    if packet.market_regime is MarketRegime.ILLIQUID:
        return TradingDecision.BLOCK, ["illiquid_market_regime"]
    if packet.market_regime is MarketRegime.UNKNOWN:
        return TradingDecision.WAIT, ["unknown_market_regime"]
    if packet.environment is TradingEnvironment.MAINNET:
        return TradingDecision.BLOCK, ["mainnet_requires_completed_security_guard_pipeline"]

    confidence = assessment.confidence * 100.0
    consensus = assessment.agreement * 100.0
    effective_confidence = min(max(float(min_confidence), 70.0), 100.0)
    effective_consensus = min(max(float(min_consensus), 70.0), 100.0)
    if confidence < effective_confidence:
        reasons.append("confidence_below_candidate_threshold")
    if consensus < effective_consensus:
        reasons.append("consensus_below_candidate_threshold")
    if len(set(item.strip() for item in packet.data_sources if item.strip())) < 3:
        reasons.append("insufficient_independent_data_sources")
    if not any(item.strip() for item in packet.signal_evidence):
        reasons.append("missing_signal_evidence")
    if reasons:
        return TradingDecision.WAIT, reasons
    return TradingDecision.ALLOW, []


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value).strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return tuple(result)


__all__ = [
    "CandidateBridgeError",
    "CandidateBuildResult",
    "CandidateEvidencePacket",
    "DecisionCandidateBridge",
]
