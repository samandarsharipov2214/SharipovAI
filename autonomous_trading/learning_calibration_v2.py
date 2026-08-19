"""Bounded advisory calibration and drift contracts for Architecture V2 learning.

This module never changes active trading policy and never grants execution
authority. Calibration observations must be explicit, protocol-bound learning
evidence. Abstentions such as WAIT are tracked separately from correctness and
never become directional labels.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from autonomous_trading.role_aware_learning_v2 import (
    LearningObjective,
    learning_objective_for_role,
)


class DriftStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    STABLE = "stable"
    DRIFTED = "drifted"


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    minimum_sample_count: int = 20
    minimum_observations_for_drift: int = 5
    max_error_deterioration: float = 0.15

    def __post_init__(self) -> None:
        if self.minimum_sample_count <= 0:
            raise ValueError("minimum_sample_count must be positive")
        if self.minimum_observations_for_drift <= 0:
            raise ValueError("minimum_observations_for_drift must be positive")
        if not 0.0 <= float(self.max_error_deterioration) <= 1.0:
            raise ValueError("max_error_deterioration must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    evidence_id: str
    role: str
    objective: LearningObjective
    confidence: float
    outcome_success: bool | None
    abstained: bool
    sample_count: int
    validation_protocol_id: str
    accepted: bool

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.role.strip():
            raise ValueError("evidence_id and role must not be empty")
        if not self.validation_protocol_id.strip():
            raise ValueError("validation_protocol_id must not be empty")
        if self.objective is not learning_objective_for_role(self.role):
            raise ValueError("calibration objective must match canonical role objective")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.abstained:
            if self.outcome_success is not None:
                raise ValueError("abstention cannot carry correctness outcome")
        elif self.outcome_success is None:
            raise ValueError("non-abstention calibration observation requires outcome_success")


@dataclass(frozen=True, slots=True)
class RoleCalibration:
    role: str
    objective: LearningObjective
    calibrated_observation_count: int = 0
    abstention_count: int = 0
    confidence_sum: float = 0.0
    outcome_sum: float = 0.0
    absolute_error_sum: float = 0.0

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("role must not be empty")
        if self.objective is not learning_objective_for_role(self.role):
            raise ValueError("role calibration objective must match canonical role objective")
        if self.calibrated_observation_count < 0 or self.abstention_count < 0:
            raise ValueError("observation counts must not be negative")
        if self.confidence_sum < 0 or self.outcome_sum < 0 or self.absolute_error_sum < 0:
            raise ValueError("calibration accumulators must not be negative")

    @property
    def mean_confidence(self) -> float | None:
        if self.calibrated_observation_count == 0:
            return None
        return self.confidence_sum / self.calibrated_observation_count

    @property
    def empirical_success_rate(self) -> float | None:
        if self.calibrated_observation_count == 0:
            return None
        return self.outcome_sum / self.calibrated_observation_count

    @property
    def mean_absolute_calibration_error(self) -> float | None:
        if self.calibrated_observation_count == 0:
            return None
        return self.absolute_error_sum / self.calibrated_observation_count


@dataclass(frozen=True, slots=True)
class CalibrationSnapshot:
    snapshot_id: str
    parent_snapshot_id: str | None
    states: tuple[RoleCalibration, ...]
    processed_evidence_ids: tuple[str, ...] = ()
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")
        if self.parent_snapshot_id is not None and not self.parent_snapshot_id.strip():
            raise ValueError("parent_snapshot_id must not be blank")
        if self.execution_authority:
            raise ValueError("calibration snapshots cannot grant execution authority")
        roles = [state.role for state in self.states]
        if len(roles) != len(set(roles)):
            raise ValueError("calibration snapshot roles must be unique")
        if len(self.processed_evidence_ids) != len(set(self.processed_evidence_ids)):
            raise ValueError("processed evidence ids must be unique")

    def state_for(self, role: str) -> RoleCalibration | None:
        for state in self.states:
            if state.role == role:
                return state
        return None


@dataclass(frozen=True, slots=True)
class CalibrationBaseline:
    role: str
    objective: LearningObjective
    mean_absolute_calibration_error: float
    observation_count: int
    validation_protocol_id: str

    def __post_init__(self) -> None:
        if not self.role.strip() or not self.validation_protocol_id.strip():
            raise ValueError("baseline role and validation_protocol_id must not be empty")
        if self.objective is not learning_objective_for_role(self.role):
            raise ValueError("baseline objective must match canonical role objective")
        if not 0.0 <= float(self.mean_absolute_calibration_error) <= 1.0:
            raise ValueError("baseline calibration error must be within [0, 1]")
        if self.observation_count <= 0:
            raise ValueError("baseline observation_count must be positive")


@dataclass(frozen=True, slots=True)
class CalibrationDriftReport:
    role: str
    objective: LearningObjective
    status: DriftStatus
    baseline_error: float
    observed_error: float | None
    deterioration: float | None
    baseline_protocol_id: str
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("drift reports cannot grant execution authority")


def empty_calibration_snapshot(*, snapshot_id: str) -> CalibrationSnapshot:
    return CalibrationSnapshot(
        snapshot_id=snapshot_id,
        parent_snapshot_id=None,
        states=(),
        execution_authority=False,
    )


def apply_calibration_observation(
    snapshot: CalibrationSnapshot,
    *,
    next_snapshot_id: str,
    observation: CalibrationObservation,
    policy: CalibrationPolicy | None = None,
) -> CalibrationSnapshot:
    """Apply one accepted observation idempotently without policy authority."""
    config = policy or CalibrationPolicy()
    if observation.evidence_id in snapshot.processed_evidence_ids:
        return snapshot
    if not observation.accepted:
        raise ValueError("calibration update requires explicitly accepted evidence")
    if observation.sample_count < config.minimum_sample_count:
        raise ValueError("calibration sample_count is below policy minimum")

    existing = snapshot.state_for(observation.role)
    if existing is None:
        existing = RoleCalibration(
            role=observation.role,
            objective=observation.objective,
        )

    if observation.abstained:
        updated = replace(existing, abstention_count=existing.abstention_count + 1)
    else:
        outcome = 1.0 if observation.outcome_success else 0.0
        confidence = float(observation.confidence)
        updated = replace(
            existing,
            calibrated_observation_count=existing.calibrated_observation_count + 1,
            confidence_sum=existing.confidence_sum + confidence,
            outcome_sum=existing.outcome_sum + outcome,
            absolute_error_sum=existing.absolute_error_sum + abs(confidence - outcome),
        )

    states = tuple(state for state in snapshot.states if state.role != observation.role) + (updated,)
    states = tuple(sorted(states, key=lambda state: state.role))
    return CalibrationSnapshot(
        snapshot_id=next_snapshot_id,
        parent_snapshot_id=snapshot.snapshot_id,
        states=states,
        processed_evidence_ids=snapshot.processed_evidence_ids + (observation.evidence_id,),
        execution_authority=False,
    )


def evaluate_calibration_drift(
    snapshot: CalibrationSnapshot,
    *,
    baseline: CalibrationBaseline,
    policy: CalibrationPolicy | None = None,
) -> CalibrationDriftReport:
    """Compare current calibration error with an explicit validated baseline."""
    config = policy or CalibrationPolicy()
    state = snapshot.state_for(baseline.role)
    if state is None or state.calibrated_observation_count < config.minimum_observations_for_drift:
        return CalibrationDriftReport(
            role=baseline.role,
            objective=baseline.objective,
            status=DriftStatus.INSUFFICIENT_EVIDENCE,
            baseline_error=float(baseline.mean_absolute_calibration_error),
            observed_error=None,
            deterioration=None,
            baseline_protocol_id=baseline.validation_protocol_id,
            execution_authority=False,
        )
    if state.objective is not baseline.objective:
        raise ValueError("current calibration objective must match baseline objective")

    observed_error = state.mean_absolute_calibration_error
    if observed_error is None:
        raise AssertionError("calibration count requires a mean error")
    deterioration = float(observed_error) - float(baseline.mean_absolute_calibration_error)
    status = (
        DriftStatus.DRIFTED
        if deterioration > config.max_error_deterioration
        else DriftStatus.STABLE
    )
    return CalibrationDriftReport(
        role=baseline.role,
        objective=baseline.objective,
        status=status,
        baseline_error=float(baseline.mean_absolute_calibration_error),
        observed_error=float(observed_error),
        deterioration=float(deterioration),
        baseline_protocol_id=baseline.validation_protocol_id,
        execution_authority=False,
    )


__all__ = [
    "CalibrationBaseline",
    "CalibrationDriftReport",
    "CalibrationObservation",
    "CalibrationPolicy",
    "CalibrationSnapshot",
    "DriftStatus",
    "RoleCalibration",
    "apply_calibration_observation",
    "empty_calibration_snapshot",
    "evaluate_calibration_drift",
]
