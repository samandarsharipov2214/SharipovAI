import pytest

from autonomous_trading.general_controller_v2 import TradingIntent
from autonomous_trading.learning_advisory_evidence_v2 import (
    ObservationValidationEvidence,
    build_advisory_learning_evidence,
)
from autonomous_trading.learning_calibration_v2 import (
    CalibrationPolicy,
    apply_calibration_observation,
    empty_calibration_snapshot,
)
from autonomous_trading.learning_observation_v2 import RoleLearningObservation
from autonomous_trading.learning_reputation_v2 import (
    ReputationPolicy,
    apply_reputation_evidence,
    empty_reputation_snapshot,
)
from autonomous_trading.role_aware_learning_v2 import LearningObjective
from autonomous_trading.settlement_posttrade_v2 import ReviewOutcome


def _observation(
    *,
    observation_id="obs-1",
    role="market_intelligence",
    objective=LearningObjective.DIRECTIONAL_QUALITY,
    entry_intent=TradingIntent.BUY,
    trade_outcome=ReviewOutcome.LOSS,
    role_success=True,
    abstained=False,
):
    return RoleLearningObservation(
        observation_id=observation_id,
        settlement_id="settlement-1",
        role=role,
        objective=objective,
        entry_intent=entry_intent,
        exit_intent=TradingIntent.SELL,
        trade_outcome=trade_outcome,
        role_success=role_success,
        abstained=abstained,
        source_evidence_ids=("market-evidence-1",),
        execution_authority=False,
    )


def _validation(**overrides):
    values = dict(
        evidence_id="validation-1",
        observation_id="obs-1",
        validation_protocol_id="learning-validation-v3",
        sample_count=20,
        confidence=0.8,
        accepted=True,
        reputation_score_delta=0.02,
    )
    values.update(overrides)
    return ObservationValidationEvidence(**values)


def test_losing_buy_keeps_explicit_directional_success_instead_of_pnl_label():
    evidence = build_advisory_learning_evidence(
        observation=_observation(trade_outcome=ReviewOutcome.LOSS, role_success=True),
        validation=_validation(reputation_score_delta=0.01),
    )

    assert evidence.calibration.outcome_success is True
    assert evidence.reputation is not None
    assert evidence.reputation.score_delta == pytest.approx(0.01)
    assert evidence.execution_authority is False


def test_profitable_trade_can_preserve_explicit_directional_failure():
    evidence = build_advisory_learning_evidence(
        observation=_observation(trade_outcome=ReviewOutcome.PROFIT, role_success=False),
        validation=_validation(reputation_score_delta=-0.01),
    )

    assert evidence.calibration.outcome_success is False
    assert evidence.reputation is not None
    assert evidence.reputation.score_delta == pytest.approx(-0.01)


def test_wait_abstention_never_creates_correctness_or_reputation_evidence():
    evidence = build_advisory_learning_evidence(
        observation=_observation(
            entry_intent=TradingIntent.WAIT,
            trade_outcome=ReviewOutcome.FLAT,
            role_success=None,
            abstained=True,
        ),
        validation=_validation(reputation_score_delta=None),
    )

    assert evidence.calibration.abstained is True
    assert evidence.calibration.outcome_success is None
    assert evidence.reputation is None


def test_veto_role_retains_veto_quality_objective():
    evidence = build_advisory_learning_evidence(
        observation=_observation(
            role="risk_engine",
            objective=LearningObjective.VETO_QUALITY,
            role_success=True,
        ),
        validation=_validation(reputation_score_delta=0.01),
    )

    assert evidence.calibration.objective is LearningObjective.VETO_QUALITY
    assert evidence.reputation is not None
    assert evidence.reputation.objective is LearningObjective.VETO_QUALITY


def test_validation_must_bind_exact_observation_id():
    with pytest.raises(ValueError, match="observation_id"):
        build_advisory_learning_evidence(
            observation=_observation(),
            validation=_validation(observation_id="different-observation"),
        )


def test_non_abstention_requires_explicit_reputation_delta():
    with pytest.raises(ValueError, match="reputation_score_delta"):
        build_advisory_learning_evidence(
            observation=_observation(),
            validation=_validation(reputation_score_delta=None),
        )


def test_abstention_rejects_reputation_delta():
    with pytest.raises(ValueError, match="abstained"):
        build_advisory_learning_evidence(
            observation=_observation(
                entry_intent=TradingIntent.WAIT,
                trade_outcome=ReviewOutcome.FLAT,
                role_success=None,
                abstained=True,
            ),
            validation=_validation(reputation_score_delta=0.01),
        )


def test_downstream_snapshot_updates_are_idempotent_for_same_validation_evidence():
    evidence = build_advisory_learning_evidence(
        observation=_observation(role_success=False),
        validation=_validation(reputation_score_delta=-0.02),
    )

    calibration_policy = CalibrationPolicy(minimum_sample_count=20)
    calibration_0 = empty_calibration_snapshot(snapshot_id="cal-0")
    calibration_1 = apply_calibration_observation(
        calibration_0,
        next_snapshot_id="cal-1",
        observation=evidence.calibration,
        policy=calibration_policy,
    )
    calibration_duplicate = apply_calibration_observation(
        calibration_1,
        next_snapshot_id="cal-2",
        observation=evidence.calibration,
        policy=calibration_policy,
    )
    assert calibration_duplicate == calibration_1

    assert evidence.reputation is not None
    reputation_policy = ReputationPolicy(minimum_sample_count=20)
    reputation_0 = empty_reputation_snapshot(snapshot_id="rep-0")
    reputation_1 = apply_reputation_evidence(
        reputation_0,
        next_snapshot_id="rep-1",
        evidence=evidence.reputation,
        policy=reputation_policy,
    )
    reputation_duplicate = apply_reputation_evidence(
        reputation_1,
        next_snapshot_id="rep-2",
        evidence=evidence.reputation,
        policy=reputation_policy,
    )
    assert reputation_duplicate == reputation_1
