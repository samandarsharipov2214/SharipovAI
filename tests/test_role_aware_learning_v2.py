from decimal import Decimal

import pytest

from autonomous_trading.general_controller_v2 import TradingIntent
from autonomous_trading.role_aware_learning_v2 import (
    LearningEvidence,
    LearningObjective,
    LessonStage,
    ValidationGate,
    directional_correctness_eligible,
    learning_objective_for_role,
    promote_lesson,
    propose_lesson,
)
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
        contributing_agents=("market_intelligence", "news_intelligence"),
        gate_verdicts=(("risk_engine", "PASS"), ("security_guard", "PASS")),
        evidence_ids=("market-1", "news-1"),
    )
    return build_review(
        settlement_id="settlement-1",
        symbol="BTCUSDT",
        fill=fill,
        lineage=lineage,
        attribution=attribution,
    )


def _validation_evidence(
    *,
    lesson,
    gate: ValidationGate,
    evidence_id: str,
    replay_delta: float | None = None,
    shadow_delta: float | None = None,
    accepted: bool = True,
    role: str | None = None,
) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        review_id=lesson.source_review_ids[0],
        role=role or lesson.role,
        hypothesis=lesson.hypothesis,
        sample_count=25,
        replay_score_delta=replay_delta,
        shadow_score_delta=shadow_delta,
        validation_gate=gate,
        validation_protocol_id=f"{gate.value}-protocol-v1",
        accepted=accepted,
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
    assert lesson.objective is LearningObjective.DIRECTIONAL_QUALITY
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


def test_canonical_market_news_and_gate_roles_keep_separate_learning_objectives() -> None:
    attribution = CounterfactualAttribution(
        market_intelligence_error=True,
        news_intelligence_error=True,
        risk_error=True,
        security_error=True,
        sizing_error=True,
        controller_synthesis_error=True,
    )
    assert attribution.implicated_roles == (
        "market_intelligence",
        "news_intelligence",
        "portfolio_engine",
        "risk_engine",
        "security_guard",
        "general_controller",
    )

    assert learning_objective_for_role("market_intelligence") is LearningObjective.DIRECTIONAL_QUALITY
    assert learning_objective_for_role("news_intelligence") is LearningObjective.DIRECTIONAL_QUALITY
    assert learning_objective_for_role("general_controller") is LearningObjective.CONTROLLER_SYNTHESIS
    assert learning_objective_for_role("risk_engine") is LearningObjective.VETO_QUALITY
    assert learning_objective_for_role("security_guard") is LearningObjective.VETO_QUALITY
    assert learning_objective_for_role("portfolio_engine") is LearningObjective.POSITION_SIZING

    assert directional_correctness_eligible("market_intelligence") is True
    assert directional_correctness_eligible("news_intelligence") is True
    assert directional_correctness_eligible("risk_engine") is False
    assert directional_correctness_eligible("security_guard") is False
    assert directional_correctness_eligible("portfolio_engine") is False
    assert directional_correctness_eligible("general_controller") is False


def test_veto_role_lesson_cannot_be_misclassified_as_directional_learning() -> None:
    review = _review(attribution=CounterfactualAttribution(risk_error=True, security_error=True))

    risk_lesson = propose_lesson(
        lesson_id="lesson-risk",
        review=review,
        role="risk_engine",
        hypothesis="tighten veto evidence under this failure mode",
        evidence_id="learning-evidence-risk",
    )
    security_lesson = propose_lesson(
        lesson_id="lesson-security",
        review=review,
        role="security_guard",
        hypothesis="improve security veto coverage",
        evidence_id="learning-evidence-security",
    )

    assert risk_lesson.objective is LearningObjective.VETO_QUALITY
    assert security_lesson.objective is LearningObjective.VETO_QUALITY
    assert directional_correctness_eligible(risk_lesson.role) is False
    assert directional_correctness_eligible(security_lesson.role) is False


def test_lesson_requires_ordered_explicit_validation_evidence_before_activation() -> None:
    review = _review(attribution=CounterfactualAttribution(controller_synthesis_error=True))
    candidate = propose_lesson(
        lesson_id="lesson-1",
        review=review,
        role="general_controller",
        hypothesis="prefer WAIT under this contradiction",
        evidence_id="learning-evidence-1",
    )

    assert candidate.objective is LearningObjective.CONTROLLER_SYNTHESIS

    with pytest.raises(ValueError, match="invalid lesson transition"):
        promote_lesson(candidate, target=LessonStage.SHADOW_VALIDATED)

    with pytest.raises(ValueError, match="explicit LearningEvidence"):
        promote_lesson(candidate, target=LessonStage.REPLAY_VALIDATED, replay_score_delta=0.15)

    replay_evidence = _validation_evidence(
        lesson=candidate,
        gate=ValidationGate.REPLAY,
        evidence_id="replay-evidence-1",
        replay_delta=0.15,
    )
    replay_validated = promote_lesson(
        candidate,
        target=LessonStage.REPLAY_VALIDATED,
        validation_evidence=replay_evidence,
        replay_score_delta=0.15,
    )
    assert replay_validated.stage is LessonStage.REPLAY_VALIDATED
    assert replay_validated.replay_score_delta == 0.15
    assert replay_validated.replay_validation_evidence_ids == ("replay-evidence-1",)

    with pytest.raises(ValueError, match="explicit LearningEvidence"):
        promote_lesson(replay_validated, target=LessonStage.SHADOW_VALIDATED, shadow_score_delta=0.05)

    shadow_evidence = _validation_evidence(
        lesson=replay_validated,
        gate=ValidationGate.SHADOW,
        evidence_id="shadow-evidence-1",
        shadow_delta=0.05,
    )
    shadow_validated = promote_lesson(
        replay_validated,
        target=LessonStage.SHADOW_VALIDATED,
        validation_evidence=shadow_evidence,
        shadow_score_delta=0.05,
    )
    assert shadow_validated.stage is LessonStage.SHADOW_VALIDATED
    assert shadow_validated.shadow_score_delta == 0.05
    assert shadow_validated.shadow_validation_evidence_ids == ("shadow-evidence-1",)

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


def test_validation_evidence_must_match_role_gate_acceptance_and_score() -> None:
    review = _review(attribution=CounterfactualAttribution(controller_synthesis_error=True))
    candidate = propose_lesson(
        lesson_id="lesson-controller",
        review=review,
        role="general_controller",
        hypothesis="wait under unresolved contradiction",
        evidence_id="learning-evidence-controller",
    )

    wrong_role = _validation_evidence(
        lesson=candidate,
        gate=ValidationGate.REPLAY,
        evidence_id="replay-wrong-role",
        replay_delta=0.2,
        role="risk_engine",
    )
    with pytest.raises(ValueError, match="role must match"):
        promote_lesson(candidate, target=LessonStage.REPLAY_VALIDATED, validation_evidence=wrong_role)

    rejected = _validation_evidence(
        lesson=candidate,
        gate=ValidationGate.REPLAY,
        evidence_id="replay-rejected",
        replay_delta=0.2,
        accepted=False,
    )
    with pytest.raises(ValueError, match="explicitly accepted"):
        promote_lesson(candidate, target=LessonStage.REPLAY_VALIDATED, validation_evidence=rejected)

    accepted = _validation_evidence(
        lesson=candidate,
        gate=ValidationGate.REPLAY,
        evidence_id="replay-accepted",
        replay_delta=0.2,
    )
    with pytest.raises(ValueError, match="must match validation evidence"):
        promote_lesson(
            candidate,
            target=LessonStage.REPLAY_VALIDATED,
            validation_evidence=accepted,
            replay_score_delta=0.3,
        )


def test_active_lesson_cannot_be_promoted_again() -> None:
    review = _review(attribution=CounterfactualAttribution(cost_error=True))
    candidate = propose_lesson(
        lesson_id="lesson-cost",
        review=review,
        role="execution_costs",
        hypothesis="avoid high realized slippage regimes",
        evidence_id="learning-evidence-cost",
    )
    assert candidate.objective is LearningObjective.EXECUTION_COST

    replay_validated = promote_lesson(
        candidate,
        target=LessonStage.REPLAY_VALIDATED,
        validation_evidence=_validation_evidence(
            lesson=candidate,
            gate=ValidationGate.REPLAY,
            evidence_id="replay-cost",
            replay_delta=0.1,
        ),
    )
    shadow_validated = promote_lesson(
        replay_validated,
        target=LessonStage.SHADOW_VALIDATED,
        validation_evidence=_validation_evidence(
            lesson=replay_validated,
            gate=ValidationGate.SHADOW,
            evidence_id="shadow-cost",
            shadow_delta=0.1,
        ),
    )
    active = promote_lesson(
        shadow_validated,
        target=LessonStage.ACTIVE,
        activation_reason="validated in both gates",
    )

    with pytest.raises(ValueError, match="invalid lesson transition"):
        promote_lesson(active, target=LessonStage.ACTIVE, activation_reason="again")
