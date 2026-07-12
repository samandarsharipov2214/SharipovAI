"""Canonical Decision Quality owner for SharipovAI.

This service coordinates agent consensus, reputation, immutable assessment
records, and post-decision learning. It never executes orders.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from meta_ai import AgentOpinion, VALID_ACTIONS, VALID_REGIMES
from meta_ai_adapter import evaluate_agent_payloads, opinions_from_payloads, record_realized_result
from meta_ai_persistence import EVENT_NAMESPACE, MetaAIPersistenceError, PersistentMetaAI
from storage import ProjectDatabase

_ASSESSMENT_EVIDENCE_CLASSES = {
    "verified_market",
    "verified_exchange",
    "verified_bybit",
    "verified_market_and_news",
    "verified_news",
    "verified_portfolio",
    "verified_risk",
    "verified_security",
}


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

    def __post_init__(self) -> None:
        clean_id = _decision_id(self.decision_id)
        action = str(self.action).upper().strip()
        regime = str(self.regime).strip()
        if action not in VALID_ACTIONS:
            raise MetaAIPersistenceError(f"stored assessment action is invalid: {action}")
        if regime not in VALID_REGIMES:
            raise MetaAIPersistenceError(f"stored assessment regime is invalid: {regime}")
        confidence = _ratio(self.confidence, "confidence")
        agreement = _ratio(self.agreement, "agreement")
        quality_score = _ratio(self.quality_score, "quality_score")
        if not isinstance(self.blocked, bool):
            raise MetaAIPersistenceError("stored assessment blocked must be boolean")
        if not isinstance(self.weighted_scores, dict):
            raise MetaAIPersistenceError("stored weighted_scores must be a dictionary")
        weighted: dict[str, float] = {}
        for key, value in self.weighted_scores.items():
            clean_key = str(key).upper().strip()
            if clean_key not in VALID_ACTIONS:
                raise MetaAIPersistenceError(f"stored weighted score action is invalid: {clean_key}")
            parsed = _finite(value, f"weighted_scores.{clean_key}")
            if parsed < 0:
                raise MetaAIPersistenceError("stored weighted scores must be non-negative")
            weighted[clean_key] = parsed
        try:
            created = datetime.fromisoformat(str(self.created_at))
        except (TypeError, ValueError) as exc:
            raise MetaAIPersistenceError("stored assessment created_at is invalid") from exc
        if created.tzinfo is None:
            raise MetaAIPersistenceError("stored assessment created_at must be timezone-aware")
        object.__setattr__(self, "decision_id", clean_id)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "agreement", agreement)
        object.__setattr__(self, "quality_score", quality_score)
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "weighted_scores", weighted)
        object.__setattr__(self, "dissenting_agents", _clean_ids(self.dissenting_agents))
        object.__setattr__(self, "rejected_agents", _clean_ids(self.rejected_agents))
        object.__setattr__(self, "regime", regime)
        object.__setattr__(self, "created_at", created.astimezone(UTC).isoformat())

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _decision_id(self.decision_id))
        selected = str(self.selected_action).upper().strip()
        realized = str(self.realized_action).upper().strip()
        if selected not in VALID_ACTIONS or realized not in VALID_ACTIONS:
            raise MetaAIPersistenceError("settlement actions must be canonical")
        if not isinstance(self.reputation_recorded, bool):
            raise MetaAIPersistenceError("reputation_recorded must be boolean")
        object.__setattr__(self, "selected_action", selected)
        object.__setattr__(self, "realized_action", realized)
        object.__setattr__(self, "winning_agents", _clean_ids(self.winning_agents))
        object.__setattr__(self, "losing_agents", _clean_ids(self.losing_agents))
        object.__setattr__(self, "abstaining_agents", _clean_ids(self.abstaining_agents))
        object.__setattr__(self, "lessons", tuple(str(item).strip() for item in self.lessons if str(item).strip()))

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
            limit=2,
        )
        if not events:
            return None
        if len(events) != 1:
            raise MetaAIPersistenceError("decision assessment history is not immutable")
        payload = events[0].get("payload", {})
        if not isinstance(payload, Mapping):
            raise MetaAIPersistenceError("stored decision assessment payload is invalid")
        if payload.get("execution_authority") is not False or payload.get("owner") != "decision_quality":
            raise MetaAIPersistenceError("stored decision assessment ownership is invalid")
        assessment = _assessment_from_payload(payload.get("assessment"))
        if assessment.decision_id != clean_id:
            raise MetaAIPersistenceError("stored decision assessment id mismatch")
        return assessment

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

        eligible, _ = _split_payloads(payloads, learning=True)
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
            "accepted_evidence_classes": sorted(_ASSESSMENT_EVIDENCE_CLASSES),
            "persistence": self.meta.persistence_status(),
        }


def _split_payloads(
    payloads: Sequence[Mapping[str, Any]],
    *,
    learning: bool = False,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    eligible: list[Mapping[str, Any]] = []
    rejected: list[str] = []
    learning_classes = {
        "verified_market",
        "verified_exchange",
        "verified_bybit",
        "verified_market_and_news",
    }
    allowed = learning_classes if learning else _ASSESSMENT_EVIDENCE_CLASSES
    for index, payload in enumerate(payloads):
        if not isinstance(payload, Mapping):
            rejected.append(f"agent-{index}")
            continue
        agent_id = str(payload.get("agent_id") or payload.get("name") or f"agent-{index}").strip()
        evidence_class = str(payload.get("evidence_class") or "").strip().lower()
        explicitly_verified = any(
            payload.get(field) is True
            for field in ("verified_market_data", "data_verified", "evidence_verified")
        )
        explicitly_ineligible = any(
            payload.get(field) is False
            for field in ("learning_eligible", "evidence_eligible", "reputation_eligible")
        )
        if not agent_id or evidence_class not in allowed or not explicitly_verified or explicitly_ineligible:
            rejected.append(agent_id or f"agent-{index}")
            continue
        eligible.append(payload)
    return eligible, tuple(sorted(set(rejected)))  # type: ignore[return-value]


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
        confidence=_finite(raw.get("confidence", 0.0), "confidence"),
        agreement=_finite(raw.get("agreement", 0.0), "agreement"),
        quality_score=_finite(raw.get("quality_score", 0.0), "quality_score"),
        blocked=raw.get("blocked", True),
        reason=str(raw.get("reason", "")),
        weighted_scores={str(key): _finite(value, f"weighted_scores.{key}") for key, value in weighted.items()},
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
    if not all(char.isalnum() or char in "._:-" for char in clean):
        raise ValueError("decision_id contains unsupported characters")
    return clean


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise MetaAIPersistenceError(f"{name} must be finite")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MetaAIPersistenceError(f"{name} must be finite") from exc
    if not math.isfinite(parsed):
        raise MetaAIPersistenceError(f"{name} must be finite")
    return parsed


def _ratio(value: object, name: str) -> float:
    parsed = _finite(value, name)
    if not 0.0 <= parsed <= 1.0:
        raise MetaAIPersistenceError(f"{name} must be within 0..1")
    return parsed


def _clean_ids(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in result:
            result.append(clean)
    return tuple(result)


__all__ = [
    "DecisionQualityAssessment",
    "DecisionQualityService",
    "DecisionSettlement",
]
