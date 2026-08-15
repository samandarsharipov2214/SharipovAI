from decimal import Decimal

import pytest

from autonomous_trading.general_controller_v2 import TradingIntent
from autonomous_trading.role_aware_learning_v2 import LessonStage, promote_lesson, propose_lesson
from autonomous_trading.settlement_posttrade_v2 import (
    CounterfactualAttribution,
    DecisionLineage,
    PositionSide,
    SettlementFill,
    build_review,
)


def _review(*, attribution: CounterfactualAttribution):
    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        entry_fee=Decimal("0.1"),
        exit_fee=Decimal("0.1"),
        realized_slippage_cost=Decimal("0.05"),
        opened_at_ms=1,
        closed_at_ms=2,
        entry_order_id="entry-1",
        exit_order_id="exit-1",
    )
    lineage = DecisionLineage(
        decision_id="decision-1",
        candidate_id="candidate-1",
        final_intent=TradingIntent.BUY,
        contributing_agents=("direction", "risk_engine"),
        gate_verdicts=(("risk_engine", "PASS"), ("security", "PASS")),
        evidence_ids=("market-1",),
    )
    return build_review(
        settlement_id="settlement-1",
        symbol="BTCUSDT",
        fill=fill,
        lineage=lineage,
        attribution=attribution,
    )


def test_propose_lesson_only_for_implicated_role() -> None:
    review = _review(attribution=CounterfactualAttribution(direction_error=True))

    lesson = propose_lesson(
        lesson_id="lesson-1",
        review=review,
        role="direction",
        hypothesis="avoid this direction pattern",
        evidence_id="learning-evidence-1",
    )

    assert lesson.stage is LessonStage.CANDIDATE
    assert lesson.role == "direction"
    assert lesson.source_review_ids == ("settlement-1",)
    assert lesson.evidence_ids == ("learning-evidence-1",)
    assert lesson.execution_authority is False

    with pytest.raises(ValueError, match="role is not implicated"):
        propose_lesson(
            lesson_id="lesson-2",
            review=review,
            role="risk_engine",
            hypothesis="unrelated risk lesson",
            evidence_id="learning-evidence-2",
        )


def test_lesson_requires_ordered_positive_validation_before_activation() -> None:
    review = _review(attribution=CounterfactualAttribution(controller_synthesis_error=True))
    candidate = propose_lesson(
        lesson_id="lesson-1",
        review=review,
        role="general_controller",
        hypothesis="prefer WAIT under this contradiction",
        evidence_id="learning-evidence-1",
    )

    with pytest.raises(ValueError, match="invalid lesson transition"):
        promote_lesson(candidate, target=LessonStage.SHADOW_VALIDATED, shadow_score_delta=0.2)

    with pytest.raises(ValueError, match="positive replay_score_delta"):
        promote_lesson(candidate, target=LessonStage.REPLAY_VALIDATED, replay_score_delta=0)

    replay_validated = promote_lesson(
        candidate,
        target=LessonStage.REPLAY_VALIDATED,
        replay_score_delta=0.15,
    )
    assert replay_validated.stage is LessonStage.REPLAY_VALIDATED
    assert replay_validated.replay_score_delta == 0.15

    with pytest.raises(ValueError, match="positive shadow_score_delta"):
        promote_lesson(replay_validated, target=LessonStage.SHADOW_VALIDATED, shadow_score_delta=-0.01)

    shadow_validated = promote_lesson(
        replay_validated,
        target=LessonStage.SHADOW_VALIDATED,
        shadow_score_delta=0.05,
    )
    assert shadow_validated.stage is LessonStage.SHADOW_VALIDATED
    assert shadow_validated.shadow_score_delta == 0.05

    with pytest.raises(ValueError, match="activation requires a reason"):
        promote_lesson(shadow_validated, target=LessonStage.ACTIVE)

    active = promote_lesson(
        shadow_validated,
        target=LessonStage.ACTIVE,
        activation_reason="replay and shadow both improved net score",
    )
    assert active.stage is LessonStage.ACTIVE
    assert active.activation_reason == "replay and shadow both improved net score"
    assert active.execution_authority is False


def test_active_lesson_cannot_be_promoted_again() -> None:
    review = _review(attribution=CounterfactualAttribution(cost_error=True))
    candidate = propose_lesson(
        lesson_id="lesson-cost",
        review=review,
        role="execution_costs",
        hypothesis="avoid high realized slippage regimes",
        evidence_id="learning-evidence-cost",
    )
    replay_validated = promote_lesson(
        candidate,
        target=LessonStage.REPLAY_VALIDATED,
        replay_score_delta=0.1,
    )
    shadow_validated = promote_lesson(
        replay_validated,
        target=LessonStage.SHADOW_VALIDATED,
        shadow_score_delta=0.1,
    )
    active = promote_lesson(
        shadow_validated,
        target=LessonStage.ACTIVE,
        activation_reason="validated in both gates",
    )

    with pytest.raises(ValueError, match="invalid lesson transition"):
        promote_lesson(active, target=LessonStage.ACTIVE, activation_reason="again")
