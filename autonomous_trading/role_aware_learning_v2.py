"""Role-aware validated learning lifecycle for Architecture V2.

This module is non-executing. Post-trade observations may propose lessons, but a
lesson cannot become active until it passes replay and shadow validation. The
module never changes trading policy or grants execution authority by itself.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from autonomous_trading.settlement_posttrade_v2 import CounterfactualAttribution, PostTradeReview


class LessonStage(StrEnum):
    CANDIDATE = "candidate"
    REPLAY_VALIDATED = "replay_validated"
    SHADOW_VALIDATED = "shadow_validated"
    ACTIVE = "active"


class LearningObjective(StrEnum):
    DIRECTIONAL_QUALITY = "directional_quality"
    EVIDENCE_QUALITY = "evidence_quality"
    CONTROLLER_SYNTHESIS = "controller_synthesis"
    VETO_QUALITY = "veto_quality"
    POSITION_SIZING = "position_sizing"
    EXECUTION_COST = "execution_cost"
    TIMING = "timing"


class ValidationGate(StrEnum):
    REPLAY = "replay"
    SHADOW = "shadow"


_ALLOWED_TRANSITIONS: dict[LessonStage, tuple[LessonStage, ...]] = {
    LessonStage.CANDIDATE: (LessonStage.REPLAY_VALIDATED,),
    LessonStage.REPLAY_VALIDATED: (LessonStage.SHADOW_VALIDATED,),
    LessonStage.SHADOW_VALIDATED: (LessonStage.ACTIVE,),
    LessonStage.ACTIVE: (),
}

_ROLE_OBJECTIVES: dict[str, LearningObjective] = {
    "market_intelligence": LearningObjective.DIRECTIONAL_QUALITY,
    "news_intelligence": LearningObjective.DIRECTIONAL_QUALITY,
    "general_controller": LearningObjective.CONTROLLER_SYNTHESIS,
    "risk_engine": LearningObjective.VETO_QUALITY,
    "security_guard": LearningObjective.VETO_QUALITY,
    "portfolio_engine": LearningObjective.POSITION_SIZING,
    "execution_costs": LearningObjective.EXECUTION_COST,
    "direction": LearningObjective.DIRECTIONAL_QUALITY,
    "evidence": LearningObjective.EVIDENCE_QUALITY,
    "timing": LearningObjective.TIMING,
}

_DIRECTIONAL_CORRECTNESS_ROLES = frozenset({"market_intelligence", "news_intelligence", "direction"})


@dataclass(frozen=True, slots=True)
class LearningEvidence:
    evidence_id: str
    review_id: str
    role: str
    hypothesis: str
    sample_count: int
    replay_score_delta: float | None = None
    shadow_score_delta: float | None = None
    validation_gate: ValidationGate | None = None
    validation_protocol_id: str | None = None
    accepted: bool | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.review_id.strip():
            raise ValueError("evidence_id and review_id must not be empty")
        if not self.role.strip() or not self.hypothesis.strip():
            raise ValueError("role and hypothesis must not be empty")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if self.validation_protocol_id is not None and not self.validation_protocol_id.strip():
            raise ValueError("validation_protocol_id must not be blank")


@dataclass(frozen=True, slots=True)
class ValidatedLesson:
    lesson_id: str
    role: str
    stage: LessonStage
    hypothesis: str
    source_review_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    objective: LearningObjective = LearningObjective.EVIDENCE_QUALITY
    replay_score_delta: float | None = None
    shadow_score_delta: float | None = None
    replay_validation_evidence_ids: tuple[str, ...] = ()
    shadow_validation_evidence_ids: tuple[str, ...] = ()
    activation_reason: str | None = None
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.lesson_id.strip() or not self.role.strip() or not self.hypothesis.strip():
            raise ValueError("lesson_id, role and hypothesis must not be empty")
        if not self.source_review_ids or not self.evidence_ids:
            raise ValueError("lesson must retain source reviews and evidence")
        if self.execution_authority:
            raise ValueError("learning lessons cannot grant execution authority")
        if self.stage is LessonStage.ACTIVE and not (self.activation_reason or "").strip():
            raise ValueError("active lessons require activation_reason")


def implicated_roles(attribution: CounterfactualAttribution) -> tuple[str, ...]:
    """Return only roles implicated by the post-trade counterfactual review."""
    return attribution.implicated_roles


def learning_objective_for_role(role: str) -> LearningObjective:
    """Return the bounded evaluation objective for a learning role.

    Risk and Security are evaluated on veto quality, Portfolio on sizing, and
    execution-cost logic on realized costs. They are never converted into
    directional voters merely because a trade later made or lost money.
    """

    normalized = role.strip()
    try:
        return _ROLE_OBJECTIVES[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported learning role: {normalized or '<empty>'}") from exc


def directional_correctness_eligible(role: str) -> bool:
    """Whether a role may receive directional correctness evaluation."""

    normalized = role.strip()
    if normalized not in _ROLE_OBJECTIVES:
        raise ValueError(f"unsupported learning role: {normalized or '<empty>'}")
    return normalized in _DIRECTIONAL_CORRECTNESS_ROLES


def propose_lesson(*, lesson_id: str, review: PostTradeReview, role: str, hypothesis: str, evidence_id: str) -> ValidatedLesson:
    if role not in implicated_roles(review.attribution):
        raise ValueError("role is not implicated by the post-trade attribution")
    objective = learning_objective_for_role(role)
    return ValidatedLesson(
        lesson_id=lesson_id,
        role=role,
        stage=LessonStage.CANDIDATE,
        hypothesis=hypothesis,
        source_review_ids=(review.settlement_id,),
        evidence_ids=(evidence_id,),
        objective=objective,
        execution_authority=False,
    )


def _validated_gate_evidence(
    *,
    lesson: ValidatedLesson,
    evidence: LearningEvidence | None,
    expected_gate: ValidationGate,
) -> LearningEvidence:
    if evidence is None:
        raise ValueError(f"{expected_gate.value} validation requires explicit LearningEvidence")
    if evidence.role != lesson.role:
        raise ValueError("validation evidence role must match lesson role")
    if evidence.hypothesis != lesson.hypothesis:
        raise ValueError("validation evidence hypothesis must match lesson hypothesis")
    if evidence.validation_gate is not expected_gate:
        raise ValueError(f"validation evidence gate must be {expected_gate.value}")
    if not (evidence.validation_protocol_id or "").strip():
        raise ValueError("validation evidence requires validation_protocol_id")
    if evidence.accepted is not True:
        raise ValueError("validation evidence must be explicitly accepted")
    return evidence


def promote_lesson(
    lesson: ValidatedLesson,
    *,
    target: LessonStage,
    validation_evidence: LearningEvidence | None = None,
    replay_score_delta: float | None = None,
    shadow_score_delta: float | None = None,
    activation_reason: str | None = None,
) -> ValidatedLesson:
    """Promote exactly one lifecycle step after explicit validation evidence.

    Replay and shadow promotion are evidence-bound. Score deltas are retained as
    compatibility inputs, but when supplied they must exactly match the
    immutable validation evidence instead of acting as standalone authority.
    """
    if target not in _ALLOWED_TRANSITIONS[lesson.stage]:
        raise ValueError(f"invalid lesson transition: {lesson.stage.value} -> {target.value}")

    if target is LessonStage.REPLAY_VALIDATED:
        evidence = _validated_gate_evidence(
            lesson=lesson,
            evidence=validation_evidence,
            expected_gate=ValidationGate.REPLAY,
        )
        evidence_delta = evidence.replay_score_delta
        if evidence_delta is None or evidence_delta <= 0:
            raise ValueError("replay validation requires positive replay_score_delta")
        if replay_score_delta is not None and float(replay_score_delta) != float(evidence_delta):
            raise ValueError("replay_score_delta must match validation evidence")
        return replace(
            lesson,
            stage=target,
            replay_score_delta=float(evidence_delta),
            replay_validation_evidence_ids=(evidence.evidence_id,),
        )

    if target is LessonStage.SHADOW_VALIDATED:
        if lesson.replay_score_delta is None or lesson.replay_score_delta <= 0:
            raise ValueError("shadow validation requires prior positive replay validation")
        if not lesson.replay_validation_evidence_ids:
            raise ValueError("shadow validation requires prior replay validation evidence")
        evidence = _validated_gate_evidence(
            lesson=lesson,
            evidence=validation_evidence,
            expected_gate=ValidationGate.SHADOW,
        )
        evidence_delta = evidence.shadow_score_delta
        if evidence_delta is None or evidence_delta <= 0:
            raise ValueError("shadow validation requires positive shadow_score_delta")
        if shadow_score_delta is not None and float(shadow_score_delta) != float(evidence_delta):
            raise ValueError("shadow_score_delta must match validation evidence")
        return replace(
            lesson,
            stage=target,
            shadow_score_delta=float(evidence_delta),
            shadow_validation_evidence_ids=(evidence.evidence_id,),
        )

    if target is LessonStage.ACTIVE:
        if lesson.shadow_score_delta is None or lesson.shadow_score_delta <= 0:
            raise ValueError("activation requires prior positive shadow validation")
        if not lesson.replay_validation_evidence_ids or not lesson.shadow_validation_evidence_ids:
            raise ValueError("activation requires replay and shadow validation evidence")
        if not (activation_reason or "").strip():
            raise ValueError("activation requires a reason")
        return replace(lesson, stage=target, activation_reason=activation_reason.strip())

    raise AssertionError("unreachable lesson target")


__all__ = [
    "LearningEvidence",
    "LearningObjective",
    "LessonStage",
    "ValidatedLesson",
    "ValidationGate",
    "directional_correctness_eligible",
    "implicated_roles",
    "learning_objective_for_role",
    "promote_lesson",
    "propose_lesson",
]
