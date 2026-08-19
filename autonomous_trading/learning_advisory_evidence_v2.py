"""Bridge explicit post-trade observations into bounded advisory learning evidence.

The bridge never infers directional correctness or reputation updates from PnL.
It only binds an already-explicit :class:`RoleLearningObservation` to validation
metadata that may later be consumed by the bounded calibration/reputation state.
No object in this module has execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from autonomous_trading.learning_calibration_v2 import CalibrationObservation
from autonomous_trading.learning_observation_v2 import RoleLearningObservation
from autonomous_trading.learning_reputation_v2 import ReputationEvidence


@dataclass(frozen=True, slots=True)
class ObservationValidationEvidence:
    """Explicit validation metadata for one role-learning observation.

    ``reputation_score_delta`` is deliberately supplied by the validating
    protocol rather than derived from trade outcome or role success. Abstentions
    never create reputation evidence.
    """

    evidence_id: str
    observation_id: str
    validation_protocol_id: str
    sample_count: int
    confidence: float
    accepted: bool
    reputation_score_delta: float | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.observation_id.strip():
            raise ValueError("evidence_id and observation_id must not be empty")
        if not self.validation_protocol_id.strip():
            raise ValueError("validation_protocol_id must not be empty")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        confidence = float(self.confidence)
        if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be finite and within [0, 1]")
        if self.reputation_score_delta is not None and not isfinite(float(self.reputation_score_delta)):
            raise ValueError("reputation_score_delta must be finite")


@dataclass(frozen=True, slots=True)
class AdvisoryLearningEvidence:
    observation_id: str
    calibration: CalibrationObservation
    reputation: ReputationEvidence | None
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id must not be empty")
        if self.execution_authority:
            raise ValueError("advisory learning evidence cannot grant execution authority")


def build_advisory_learning_evidence(
    *,
    observation: RoleLearningObservation,
    validation: ObservationValidationEvidence,
) -> AdvisoryLearningEvidence:
    """Build calibration/reputation evidence without PnL-derived labels.

    The observation already contains an explicit role-specific success value.
    This function preserves that value exactly. PROFIT/LOSS/FLAT is not read at
    all when constructing either downstream evidence object.
    """

    if validation.observation_id != observation.observation_id:
        raise ValueError("validation observation_id must match learning observation")

    calibration = CalibrationObservation(
        evidence_id=validation.evidence_id,
        role=observation.role,
        objective=observation.objective,
        confidence=float(validation.confidence),
        outcome_success=observation.role_success,
        abstained=observation.abstained,
        sample_count=validation.sample_count,
        validation_protocol_id=validation.validation_protocol_id,
        accepted=validation.accepted,
    )

    reputation: ReputationEvidence | None = None
    if observation.abstained:
        if validation.reputation_score_delta is not None:
            raise ValueError("abstained observation cannot create reputation evidence")
    else:
        if validation.reputation_score_delta is None:
            raise ValueError("non-abstention validation requires explicit reputation_score_delta")
        reputation = ReputationEvidence(
            evidence_id=validation.evidence_id,
            role=observation.role,
            objective=observation.objective,
            score_delta=float(validation.reputation_score_delta),
            sample_count=validation.sample_count,
            validation_protocol_id=validation.validation_protocol_id,
            accepted=validation.accepted,
        )

    return AdvisoryLearningEvidence(
        observation_id=observation.observation_id,
        calibration=calibration,
        reputation=reputation,
        execution_authority=False,
    )


__all__ = [
    "AdvisoryLearningEvidence",
    "ObservationValidationEvidence",
    "build_advisory_learning_evidence",
]
