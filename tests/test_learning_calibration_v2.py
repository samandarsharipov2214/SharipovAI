from __future__ import annotations

import pytest

from autonomous_trading.learning_calibration_v2 import (
    CalibrationBaseline,
    CalibrationObservation,
    CalibrationPolicy,
    DriftStatus,
    apply_calibration_observation,
    empty_calibration_snapshot,
    evaluate_calibration_drift,
)
from autonomous_trading.role_aware_learning_v2 import LearningObjective


def _observation(
    *,
    evidence_id: str,
    role: str = "market_intelligence",
    objective: LearningObjective = LearningObjective.DIRECTIONAL_QUALITY,
    confidence: float = 0.8,
    outcome_success: bool | None = True,
    abstained: bool = False,
    sample_count: int = 20,
    accepted: bool = True,
) -> CalibrationObservation:
    return CalibrationObservation(
        evidence_id=evidence_id,
        role=role,
        objective=objective,
        confidence=confidence,
        outcome_success=outcome_success,
        abstained=abstained,
        sample_count=sample_count,
        validation_protocol_id="shadow-calibration-v1",
        accepted=accepted,
    )


def test_wait_abstention_is_not_directional_correctness_observation() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")
    updated = apply_calibration_observation(
        snapshot,
        next_snapshot_id="calibration-1",
        observation=_observation(
            evidence_id="wait-1",
            confidence=0.61,
            outcome_success=None,
            abstained=True,
        ),
    )

    state = updated.state_for("market_intelligence")
    assert state is not None
    assert state.abstention_count == 1
    assert state.calibrated_observation_count == 0
    assert state.mean_confidence is None
    assert state.empirical_success_rate is None
    assert state.mean_absolute_calibration_error is None
    assert updated.execution_authority is False


def test_abstention_cannot_carry_profit_or_loss_correctness_label() -> None:
    with pytest.raises(ValueError, match="abstention cannot carry correctness outcome"):
        _observation(
            evidence_id="wait-invalid",
            outcome_success=False,
            abstained=True,
        )


def test_veto_role_keeps_veto_quality_objective() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")
    updated = apply_calibration_observation(
        snapshot,
        next_snapshot_id="calibration-1",
        observation=_observation(
            evidence_id="risk-1",
            role="risk_engine",
            objective=LearningObjective.VETO_QUALITY,
            confidence=0.9,
            outcome_success=True,
        ),
    )

    state = updated.state_for("risk_engine")
    assert state is not None
    assert state.objective is LearningObjective.VETO_QUALITY
    assert state.calibrated_observation_count == 1

    with pytest.raises(ValueError, match="canonical role objective"):
        _observation(
            evidence_id="risk-wrong-objective",
            role="risk_engine",
            objective=LearningObjective.DIRECTIONAL_QUALITY,
        )


def test_calibration_observation_requires_accepted_protocol_bound_sample() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")

    with pytest.raises(ValueError, match="explicitly accepted"):
        apply_calibration_observation(
            snapshot,
            next_snapshot_id="calibration-1",
            observation=_observation(evidence_id="rejected", accepted=False),
        )

    with pytest.raises(ValueError, match="below policy minimum"):
        apply_calibration_observation(
            snapshot,
            next_snapshot_id="calibration-1",
            observation=_observation(evidence_id="too-small", sample_count=19),
        )

    with pytest.raises(ValueError, match="confidence must be within"):
        _observation(evidence_id="bad-confidence", confidence=1.01)


def test_duplicate_calibration_evidence_is_idempotent() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")
    observation = _observation(evidence_id="market-1", confidence=0.8, outcome_success=True)

    first = apply_calibration_observation(
        snapshot,
        next_snapshot_id="calibration-1",
        observation=observation,
    )
    duplicate = apply_calibration_observation(
        first,
        next_snapshot_id="calibration-2",
        observation=observation,
    )

    assert duplicate is first
    state = duplicate.state_for("market_intelligence")
    assert state is not None
    assert state.calibrated_observation_count == 1
    assert duplicate.processed_evidence_ids == ("market-1",)


def test_drift_requires_enough_non_abstention_evidence() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")
    baseline = CalibrationBaseline(
        role="market_intelligence",
        objective=LearningObjective.DIRECTIONAL_QUALITY,
        mean_absolute_calibration_error=0.1,
        observation_count=100,
        validation_protocol_id="sealed-baseline-v1",
    )

    for index in range(4):
        snapshot = apply_calibration_observation(
            snapshot,
            next_snapshot_id=f"calibration-{index + 1}",
            observation=_observation(
                evidence_id=f"market-{index}",
                confidence=0.8,
                outcome_success=True,
            ),
        )

    report = evaluate_calibration_drift(snapshot, baseline=baseline)
    assert report.status is DriftStatus.INSUFFICIENT_EVIDENCE
    assert report.observed_error is None
    assert report.deterioration is None
    assert report.execution_authority is False


def test_drift_report_is_baseline_bound_and_advisory_only() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")
    baseline = CalibrationBaseline(
        role="market_intelligence",
        objective=LearningObjective.DIRECTIONAL_QUALITY,
        mean_absolute_calibration_error=0.1,
        observation_count=100,
        validation_protocol_id="sealed-baseline-v1",
    )
    policy = CalibrationPolicy(
        minimum_sample_count=20,
        minimum_observations_for_drift=5,
        max_error_deterioration=0.15,
    )

    for index in range(5):
        snapshot = apply_calibration_observation(
            snapshot,
            next_snapshot_id=f"calibration-{index + 1}",
            observation=_observation(
                evidence_id=f"market-loss-{index}",
                confidence=0.9,
                outcome_success=False,
            ),
            policy=policy,
        )

    report = evaluate_calibration_drift(snapshot, baseline=baseline, policy=policy)
    assert report.status is DriftStatus.DRIFTED
    assert report.baseline_protocol_id == "sealed-baseline-v1"
    assert report.observed_error == pytest.approx(0.9)
    assert report.deterioration == pytest.approx(0.8)
    assert report.execution_authority is False


def test_stable_calibration_does_not_claim_drift() -> None:
    snapshot = empty_calibration_snapshot(snapshot_id="calibration-0")
    baseline = CalibrationBaseline(
        role="news_intelligence",
        objective=LearningObjective.DIRECTIONAL_QUALITY,
        mean_absolute_calibration_error=0.2,
        observation_count=100,
        validation_protocol_id="sealed-news-baseline-v1",
    )

    for index in range(5):
        snapshot = apply_calibration_observation(
            snapshot,
            next_snapshot_id=f"calibration-{index + 1}",
            observation=_observation(
                evidence_id=f"news-{index}",
                role="news_intelligence",
                confidence=0.8,
                outcome_success=True,
            ),
        )

    report = evaluate_calibration_drift(snapshot, baseline=baseline)
    assert report.status is DriftStatus.STABLE
    assert report.observed_error == pytest.approx(0.2)
    assert report.deterioration == pytest.approx(0.0)
