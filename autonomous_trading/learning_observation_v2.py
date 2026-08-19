"""Explicit post-trade learning observations for SharipovAI V2/V3.

This bridge keeps trade outcome, entry/exit direction, and role-specific learning
quality separate. It never infers BUY/SELL correctness from the sign of PnL and
never grants execution authority. A candidate lesson may be proposed only from
an explicit failed role assessment; successful or abstained observations do not
automatically mutate policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from autonomous_trading.general_controller_v2 import TradingIntent
from autonomous_trading.role_aware_learning_v2 import (
    LearningObjective,
    ValidatedLesson,
    learning_objective_for_role,
    propose_lesson,
)
from autonomous_trading.settlement_posttrade_v2 import PostTradeReview, ReviewOutcome


@dataclass(frozen=True, slots=True)
class RoleLearningAssessment:
    """Explicit role-quality assessment bound to one post-trade review.

    ``success`` is objective-specific and must be supplied by the caller. It is
    deliberately independent from ``review.outcome`` so a losing BUY can still
    be a correct directional call if the role-specific evaluation proves that.
    ``abstained`` models WAIT/no-op evidence and never carries correctness.
    """

    role: str
    evidence_id: str
    success: bool | None
    abstained: bool = False

    def __post_init__(self) -> None:
        if not self.role.strip() or not self.evidence_id.strip():
            raise ValueError("role and evidence_id must not be empty")
        learning_objective_for_role(self.role)
        if self.abstained:
            if self.success is not None:
                raise ValueError("abstention cannot carry role correctness")
        elif self.success is None:
            raise ValueError("non-abstention assessment requires explicit success")


@dataclass(frozen=True, slots=True)
class RoleLearningObservation:
    observation_id: str
    settlement_id: str
    role: str
    objective: LearningObjective
    entry_intent: TradingIntent
    exit_intent: TradingIntent | None
    trade_outcome: ReviewOutcome
    role_success: bool | None
    abstained: bool
    source_evidence_ids: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.settlement_id.strip() or not self.role.strip():
            raise ValueError("observation_id, settlement_id and role must not be empty")
        if self.objective is not learning_objective_for_role(self.role):
            raise ValueError("observation objective must match canonical role objective")
        if not self.source_evidence_ids:
            raise ValueError("learning observation must retain source evidence")
        if len(self.source_evidence_ids) != len(set(self.source_evidence_ids)):
            raise ValueError("source_evidence_ids must be unique")
        if self.execution_authority:
            raise ValueError("learning observation cannot grant execution authority")
        if self.abstained:
            if self.role_success is not None:
                raise ValueError("abstention cannot carry role correctness")
        elif self.role_success is None:
            raise ValueError("non-abstention observation requires explicit role_success")


def build_role_learning_observation(
    *,
    review: PostTradeReview,
    assessment: RoleLearningAssessment,
) -> RoleLearningObservation:
    """Bind an explicit role assessment to immutable settlement lineage.

    The function never derives ``role_success`` from PROFIT/LOSS/FLAT. The trade
    outcome is retained only as separate context for later counterfactual review.
    """

    if assessment.role not in review.attribution.implicated_roles:
        raise ValueError("role is not implicated by post-trade attribution")

    evidence_ids = tuple(
        dict.fromkeys(
            review.lineage.evidence_ids
            + review.lineage.exit_evidence_ids
            + (assessment.evidence_id,)
        )
    )
    digest = sha256(
        "\n".join(
            (
                "learning-observation-v1",
                review.settlement_id,
                assessment.role,
                assessment.evidence_id,
            )
        ).encode("utf-8")
    ).hexdigest()
    return RoleLearningObservation(
        observation_id=digest,
        settlement_id=review.settlement_id,
        role=assessment.role,
        objective=learning_objective_for_role(assessment.role),
        entry_intent=review.lineage.entry_intent,
        exit_intent=review.lineage.exit_intent,
        trade_outcome=review.outcome,
        role_success=assessment.success,
        abstained=assessment.abstained,
        source_evidence_ids=evidence_ids,
        execution_authority=False,
    )


def propose_lesson_from_failed_observation(
    *,
    review: PostTradeReview,
    observation: RoleLearningObservation,
    lesson_id: str,
    hypothesis: str,
) -> ValidatedLesson:
    """Create a candidate lesson only from an explicit failed role assessment."""

    if observation.settlement_id != review.settlement_id:
        raise ValueError("observation settlement_id must match review settlement_id")
    if observation.role not in review.attribution.implicated_roles:
        raise ValueError("observation role is not implicated by post-trade attribution")
    if observation.abstained:
        raise ValueError("abstained observation cannot automatically propose a lesson")
    if observation.role_success is not False:
        raise ValueError("candidate lesson requires explicit failed role assessment")
    if observation.objective is not learning_objective_for_role(observation.role):
        raise ValueError("observation objective must match canonical role objective")

    return propose_lesson(
        lesson_id=lesson_id,
        review=review,
        role=observation.role,
        hypothesis=hypothesis,
        evidence_id=observation.observation_id,
    )


__all__ = [
    "RoleLearningAssessment",
    "RoleLearningObservation",
    "build_role_learning_observation",
    "propose_lesson_from_failed_observation",
]
