from __future__ import annotations

from decimal import Decimal

import pytest

from autonomous_trading.general_controller_v2 import TradingIntent
from autonomous_trading.learning_observation_v2 import (
    RoleLearningAssessment,
    build_role_learning_observation,
    propose_lesson_from_failed_observation,
)
from autonomous_trading.role_aware_learning_v2 import LearningObjective, LessonStage
from autonomous_trading.settlement_posttrade_v2 import (
    CounterfactualAttribution,
    DecisionLineage,
    PositionSide,
    ReviewOutcome,
    SettlementFill,
    build_review,
)


def _review(
    *,
    exit_price: str,
    attribution: CounterfactualAttribution,
):
    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal(exit_price),
        entry_fee=Decimal("0.1"),
        exit_fee=Decimal("0.1"),
        realized_slippage_cost=Decimal("0.1"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        entry_order_id="entry-1",
        exit_order_id="exit-1",
    )
    lineage = DecisionLineage(
        decision_id="entry-decision-1",
        candidate_id="candidate-1",
        final_intent=TradingIntent.BUY,
        contributing_agents=("market_intelligence", "news_intelligence"),
        gate_verdicts=(("risk_engine", "PASS"), ("security_guard", "PASS")),
        evidence_ids=("market-entry", "news-entry"),
        exit_decision_id="exit-decision-1",
        exit_intent=TradingIntent.SELL,
        exit_evidence_ids=("market-exit",),
    )
    return build_review(
        settlement_id="settlement-1",
        symbol="BTCUSDT",
        fill=fill,
        lineage=lineage,
        attribution=attribution,
    )


def test_losing_buy_can_remain_explicitly_directionally_correct() -> None:
    review = _review(
        exit_price="95",
        attribution=CounterfactualAttribution(market_intelligence_error=True),
    )
    observation = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="market_intelligence",
            evidence_id="direction-eval-1",
            success=True,
        ),
    )

    assert review.outcome is ReviewOutcome.LOSS
    assert observation.trade_outcome is ReviewOutcome.LOSS
    assert observation.entry_intent is TradingIntent.BUY
    assert observation.exit_intent is TradingIntent.SELL
    assert observation.role_success is True
    assert observation.objective is LearningObjective.DIRECTIONAL_QUALITY
    assert observation.execution_authority is False


def test_profitable_trade_can_still_have_explicit_directional_failure() -> None:
    review = _review(
        exit_price="110",
        attribution=CounterfactualAttribution(news_intelligence_error=True),
    )
    observation = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="news_intelligence",
            evidence_id="news-eval-1",
            success=False,
        ),
    )

    assert review.outcome is ReviewOutcome.PROFIT
    assert observation.trade_outcome is ReviewOutcome.PROFIT
    assert observation.role_success is False
    assert observation.entry_intent is TradingIntent.BUY
    assert observation.objective is LearningObjective.DIRECTIONAL_QUALITY


def test_wait_abstention_never_becomes_directional_correctness() -> None:
    review = _review(
        exit_price="101",
        attribution=CounterfactualAttribution(market_intelligence_error=True),
    )
    observation = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="market_intelligence",
            evidence_id="wait-eval-1",
            success=None,
            abstained=True,
        ),
    )

    assert observation.abstained is True
    assert observation.role_success is None
    assert observation.trade_outcome is ReviewOutcome.PROFIT

    with pytest.raises(ValueError, match="abstention cannot carry role correctness"):
        RoleLearningAssessment(
            role="market_intelligence",
            evidence_id="wait-invalid",
            success=False,
            abstained=True,
        )


def test_veto_roles_keep_veto_quality_objective() -> None:
    review = _review(
        exit_price="97",
        attribution=CounterfactualAttribution(risk_error=True, security_error=True),
    )
    risk = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="risk_engine",
            evidence_id="risk-eval-1",
            success=False,
        ),
    )
    security = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="security_guard",
            evidence_id="security-eval-1",
            success=True,
        ),
    )

    assert risk.objective is LearningObjective.VETO_QUALITY
    assert security.objective is LearningObjective.VETO_QUALITY
    assert risk.entry_intent is TradingIntent.BUY
    assert risk.trade_outcome is ReviewOutcome.LOSS


def test_observation_requires_implicated_role_and_preserves_unique_evidence_lineage() -> None:
    review = _review(
        exit_price="99",
        attribution=CounterfactualAttribution(market_intelligence_error=True),
    )
    with pytest.raises(ValueError, match="not implicated"):
        build_role_learning_observation(
            review=review,
            assessment=RoleLearningAssessment(
                role="risk_engine",
                evidence_id="risk-not-implicated",
                success=False,
            ),
        )

    observation = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="market_intelligence",
            evidence_id="market-entry",
            success=False,
        ),
    )
    assert observation.source_evidence_ids == (
        "market-entry",
        "news-entry",
        "market-exit",
    )


def test_candidate_lesson_requires_explicit_failed_non_abstention_observation() -> None:
    review = _review(
        exit_price="110",
        attribution=CounterfactualAttribution(controller_synthesis_error=True),
    )
    failed = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="general_controller",
            evidence_id="controller-eval-1",
            success=False,
        ),
    )
    lesson = propose_lesson_from_failed_observation(
        review=review,
        observation=failed,
        lesson_id="lesson-controller-1",
        hypothesis="improve contradiction handling",
    )

    assert lesson.stage is LessonStage.CANDIDATE
    assert lesson.objective is LearningObjective.CONTROLLER_SYNTHESIS
    assert lesson.execution_authority is False
    assert lesson.evidence_ids == (failed.observation_id,)

    successful = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="general_controller",
            evidence_id="controller-eval-success",
            success=True,
        ),
    )
    with pytest.raises(ValueError, match="explicit failed role assessment"):
        propose_lesson_from_failed_observation(
            review=review,
            observation=successful,
            lesson_id="lesson-invalid-success",
            hypothesis="must not be created",
        )

    abstained = build_role_learning_observation(
        review=review,
        assessment=RoleLearningAssessment(
            role="general_controller",
            evidence_id="controller-wait",
            success=None,
            abstained=True,
        ),
    )
    with pytest.raises(ValueError, match="abstained observation"):
        propose_lesson_from_failed_observation(
            review=review,
            observation=abstained,
            lesson_id="lesson-invalid-wait",
            hypothesis="must not be created",
        )
