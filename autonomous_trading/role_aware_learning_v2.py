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


_ALLOWED_TRANSITIONS: dict[LessonStage, tuple[LessonStage, ...]] = {
    LessonStage.CANDIDATE: (LessonStage.REPLAY_VALIDATED,),
    LessonStage.REPLAY_VALIDATED: (LessonStage.SHADOW_VALIDATED,),
    LessonStage.SHADOW_VALIDATED: (LessonStage.ACTIVE,),
    LessonStage.ACTIVE: (),
}


@dataclass(frozen=True, slots=True)
class LearningEvidence:
    evidence_id: str
    review_id: str
    role: str
    hypothesis: str
    sample_count: int
    replay_score_delta: float | None = None
    shadow_score_delta: float | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.review_id.strip():
            raise ValueError("evidence_id and review_id must not be empty")
        if not self.role.strip() or not self.hypothesis.strip():
            raise ValueError("role and hypothesis must not be empty")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")


@dataclass(frozen=True, slots=True)
class ValidatedLesson:
    lesson_id: str
    role: str
    stage: LessonStage
    hypothesis: str
    source_review_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    replay_score_delta: float | None = None
    shadow_score_delta: float | None = None
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


def propose_lesson(*, lesson_id: str, review: PostTradeReview, role: str, hypothesis: str, evidence_id: str) -> ValidatedLesson:
    if role not in implicated_roles(review.attribution):
        raise ValueError("role is not implicated by the post-trade attribution")
    return ValidatedLesson(
        lesson_id=lesson_id,
        role=role,
        stage=LessonStage.CANDIDATE,
        hypothesis=hypothesis,
        source_review_ids=(review.settlement_id,),
        evidence_ids=(evidence_id,),
        execution_authority=False,
    )


def promote_lesson(
    lesson: ValidatedLesson,
    *,
    target: LessonStage,
    replay_score_delta: float | None = None,
    shadow_score_delta: float | None = None,
    activation_reason: str | None = None,
) -> ValidatedLesson:
    """Promote exactly one lifecycle step after explicit validation evidence."""
    if target not in _ALLOWED_TRANSITIONS[lesson.stage]:
        raise ValueError(f"invalid lesson transition: {lesson.stage.value} -> {target.value}")

    if target is LessonStage.REPLAY_VALIDATED:
        if replay_score_delta is None or replay_score_delta <= 0:
            raise ValueError("replay validation requires positive replay_score_delta")
        return replace(lesson, stage=target, replay_score_delta=float(replay_score_delta))

    if target is LessonStage.SHADOW_VALIDATED:
        if lesson.replay_score_delta is None or lesson.replay_score_delta <= 0:
            raise ValueError("shadow validation requires prior positive replay validation")
        if shadow_score_delta is None or shadow_score_delta <= 0:
            raise ValueError("shadow validation requires positive shadow_score_delta")
        return replace(lesson, stage=target, shadow_score_delta=float(shadow_score_delta))

    if target is LessonStage.ACTIVE:
        if lesson.shadow_score_delta is None or lesson.shadow_score_delta <= 0:
            raise ValueError("activation requires prior positive shadow validation")
        if not (activation_reason or "").strip():
            raise ValueError("activation requires a reason")
        return replace(lesson, stage=target, activation_reason=activation_reason.strip())

    raise AssertionError("unreachable lesson target")


__all__ = [
    "LearningEvidence",
    "LessonStage",
    "ValidatedLesson",
    "implicated_roles",
    "promote_lesson",
    "propose_lesson",
]
