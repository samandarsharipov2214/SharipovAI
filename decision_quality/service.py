"""Canonical Decision Quality owner for SharipovAI.

This service coordinates agent consensus, reputation, immutable assessment
records, and post-decision learning. It never executes orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from meta_ai import AgentOpinion
from meta_ai_adapter import evaluate_agent_payloads, opinions_from_payloads, record_realized_result
from meta_ai_persistence import EVENT_NAMESPACE, MetaAIPersistenceError, PersistentMetaAI
from storage import ProjectDatabase


@dataclass(frozen=True, slots=True)
class DecisionQualityAssessment:
    decision_id: str
    action: str
    confidence: float
    agreement: float
    quality_score: float
    blocked: bool
    reason: str
    weighted_scores: dict[str, float]
    dissenting_agents: tuple[str, ...]
    rejected_agents: tuple[str, ...]
    regime: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DecisionSettlement:
    decision_id: str
    selected_action: str
    realized_action: str
    reputation_recorded: bool
    winning_agents: tuple[str, ...]
    losing_agents: tuple[str, ...]
    abstaining_agents: tuple[str, ...]
    lessons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionQualityService:
    """Single canonical owner of decision-quality assessment and learning."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        meta: PersistentMetaAI | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.meta = meta or PersistentMetaAI(self.database)
        if self.meta.database.dsn != self.database.dsn:
            raise ValueError("DecisionQualityService and PersistentMetaAI must use the same database")

    def evaluate(
        self,
        decision_id: str,
        payloads: Sequence[Mapping[str, Any]],
        *,
        regime: str = "unknown",
        min_evidence: float = 0.35,
        max_risk: float = 0.80,
        min_agreement: float = 0.55,
    ) -> DecisionQualityAssessment:
        """Evaluate and persist one immutable, idempotent council assessment."""

        clean_id = _decision_id(decision_id)
        existing = self.get_assessment(clean_id)
        if existing is not None:
            return existing

        eligible, rejected = _split_payloads(payloads)
        opinions = opinions_from_payloads(eligible, regime=regime)
        result = evaluate_agent_payloads(
            self.meta,
            eligible,
            regime=regime,
            min_evidence=min_evidence,
            max_risk=max_risk,
            min_agreement=min_agreement,
        )
        assessment = DecisionQualityAssessment(
            decision_id=clean_id,
            action=result.action,
            confidence=float(result.confidence),
            agreement=float(result.agreement),
            quality_score=float(self.meta.decision_quality_score(result)),
            blocked=bool(result.blocked),
            reason=str(result.reason),
            weighted_scores={str(key): float(value) for key, value in result.weighted_scores.items()},
            dissenting_agents=tuple(result.dissenting_agents),
            rejected_agents=tuple(rejected),
            regime=str(regime),
            created_at=datetime.now(UTC).isoformat(),
        )
        payload = {
            "assessment": assessment.to_dict(),
            "opinions": [_opinion_payload(item) for item in opinions],
            "rejected_agents": list(rejected),
            "owner": "decision_quality",
            "execution_authority": False,
        }
        try:
            self.database.append_event(
                EVENT_NAMESPACE,
                "decision_assessment",
                clean_id,
                payload,
                event_id=f"decision-assessment-{clean_id}",
            )
        except Exception:
            concurrent = self.get_assessment(clean_id)
            if concurrent is not None:
                return concurrent
            raise
        return assessment

    def get_assessment(self, decision_id: str) -> DecisionQualityAssessment | None:
        clean_id = _decision_id(decision_id)
        events = self.database.list_events(
            EVENT_NAMESPACE,
            entity_type="decision_assessment",
            entity_id=clean_id,
            limit=1,
        )
        if not events:
            return None
        payload = events[0].get("payload", {})
        if not isinstance(payload, Mapping):
            raise MetaAIPersistenceError("stored decision assessment payload is invalid")
        return _assessment_from_payload(payload.get("assessment"))

    def settle(
        self,
        decision_id: str,
        payloads: Sequence[Mapping[str, Any]],
        *,
        realized_action: str,
        pnl_by_agent: Mapping[str, float] | None = None,
        drawdown_by_agent: Mapping[str, float] | None = None,
        regime: str = "unknown",
        evidence_class: str = "verified_market",
        verified_market_data: bool = True,
    ) -> DecisionSettlement:
        """Persist verified realized outcomes and immutable post-decision audit."""

        clean_id = _decision_id(decision_id)
        assessment = self.get_assessment(clean_id)
        if assessment is None:
            raise MetaAIPersistenceError("decision must be assessed before it can be settled")

        eligible, _ = _split_payloads(payloads)
        if not eligible:
            raise MetaAIPersistenceError("no evidence-eligible agent payloads are available for settlement")

        reputation_recorded = record_realized_result(
            self.meta,
            eligible,
            realized_action=realized_action,
            pnl_by_agent=pnl_by_agent,
            drawdown_by_agent=drawdown_by_agent,
            regime=regime,
            decision_id=clean_id,
            evidence_class=evidence_class,
            verified_market_data=verified_market_data,
        )
        audit = self.meta.audit_and_persist(
            clean_id,
            opinions_from_payloads(eligible, regime=regime),
            selected_action=assessment.action,
            realized_action=realized_action,
        )
        return DecisionSettlement(
            decision_id=clean_id,
            selected_action=assessment.action,
            realized_action=str(realized_action).upper(),
            reputation_recorded=reputation_recorded,
            winning_agents=audit.winning_agents,
            losing_agents=audit.losing_agents,
            abstaining_agents=audit.abstaining_agents,
            lessons=audit.lessons,
        )

    def status(self) -> dict[str, object]:
        return {
            "owner": "decision_quality",
            "execution_authority": False,
            "persistence": self.meta.persistence_status(),
        }


def _split_payloads(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    eligible: list[Mapping[str, Any]] = []
    rejected: list[str] = []
    for index, payload in enumerate(payloads):
        agent_id = str(payload.get("agent_id") or payload.get("name") or f"agent-{index}")
        evidence_class = str(payload.get("evidence_class") or "").strip().lower()
        explicit_false = any(
            payload.get(field) is False
            for field in (
                "learning_eligible",
                "evidence_eligible",
                "reputation_eligible",
                "verified_market_data",
                "data_verified",
            )
        )
        synthetic = evidence_class in {
            "synthetic",
            "synthetic_simulation",
            "demo",
            "fixture",
            "mock",
        }
        if explicit_false or synthetic:
            rejected.append(agent_id)
        else:
            eligible.append(payload)
    return eligible, sorted(set(rejected))


def _opinion_payload(opinion: AgentOpinion) -> dict[str, object]:
    return {
        "agent_id": opinion.agent_id,
        "action": opinion.action,
        "confidence": opinion.confidence,
        "evidence_score": opinion.evidence_score,
        "risk_score": opinion.risk_score,
        "regime": opinion.regime,
        "rationale": opinion.rationale[:2_000],
    }


def _assessment_from_payload(raw: object) -> DecisionQualityAssessment:
    if not isinstance(raw, Mapping):
        raise MetaAIPersistenceError("stored decision assessment is invalid")
    weighted = raw.get("weighted_scores", {})
    if not isinstance(weighted, Mapping):
        raise MetaAIPersistenceError("stored weighted_scores must be a mapping")
    return DecisionQualityAssessment(
        decision_id=str(raw.get("decision_id", "")),
        action=str(raw.get("action", "WAIT")),
        confidence=float(raw.get("confidence", 0.0)),
        agreement=float(raw.get("agreement", 0.0)),
        quality_score=float(raw.get("quality_score", 0.0)),
        blocked=bool(raw.get("blocked", True)),
        reason=str(raw.get("reason", "")),
        weighted_scores={str(key): float(value) for key, value in weighted.items()},
        dissenting_agents=tuple(str(item) for item in raw.get("dissenting_agents", [])),
        rejected_agents=tuple(str(item) for item in raw.get("rejected_agents", [])),
        regime=str(raw.get("regime", "unknown")),
        created_at=str(raw.get("created_at", "")),
    )


def _decision_id(value: object) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError("decision_id must not be empty")
    if len(clean) > 170:
        raise ValueError("decision_id must contain at most 170 characters")
    return clean


__all__ = [
    "DecisionQualityAssessment",
    "DecisionQualityService",
    "DecisionSettlement",
]
