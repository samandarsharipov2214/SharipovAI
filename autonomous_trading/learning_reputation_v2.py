"""Bounded, immutable learning reputation state for Architecture V2.

Reputation is advisory learning metadata only. It cannot grant execution
authority or mutate an active trading policy. Updates require explicit accepted
validation evidence, are bounded per observation, and produce immutable
snapshots that can be rolled back without erasing the audit trail.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from autonomous_trading.role_aware_learning_v2 import (
    LearningObjective,
    learning_objective_for_role,
)


@dataclass(frozen=True, slots=True)
class ReputationPolicy:
    max_abs_score: float = 1.0
    max_abs_update: float = 0.05
    minimum_sample_count: int = 20

    def __post_init__(self) -> None:
        if self.max_abs_score <= 0:
            raise ValueError("max_abs_score must be positive")
        if self.max_abs_update <= 0 or self.max_abs_update > self.max_abs_score:
            raise ValueError("max_abs_update must be positive and <= max_abs_score")
        if self.minimum_sample_count <= 0:
            raise ValueError("minimum_sample_count must be positive")


@dataclass(frozen=True, slots=True)
class RoleReputation:
    role: str
    objective: LearningObjective
    score: float = 0.0
    update_count: int = 0

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("role must not be empty")
        if self.objective is not learning_objective_for_role(self.role):
            raise ValueError("role reputation objective must match canonical role objective")
        if self.update_count < 0:
            raise ValueError("update_count must not be negative")


@dataclass(frozen=True, slots=True)
class ReputationEvidence:
    evidence_id: str
    role: str
    objective: LearningObjective
    score_delta: float
    sample_count: int
    validation_protocol_id: str
    accepted: bool

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.role.strip():
            raise ValueError("evidence_id and role must not be empty")
        if not self.validation_protocol_id.strip():
            raise ValueError("validation_protocol_id must not be empty")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if self.objective is not learning_objective_for_role(self.role):
            raise ValueError("evidence objective must match canonical role objective")


@dataclass(frozen=True, slots=True)
class ReputationSnapshot:
    snapshot_id: str
    parent_snapshot_id: str | None
    states: tuple[RoleReputation, ...]
    processed_evidence_ids: tuple[str, ...] = ()
    rollback_of_snapshot_id: str | None = None
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")
        if self.parent_snapshot_id is not None and not self.parent_snapshot_id.strip():
            raise ValueError("parent_snapshot_id must not be blank")
        if self.rollback_of_snapshot_id is not None and not self.rollback_of_snapshot_id.strip():
            raise ValueError("rollback_of_snapshot_id must not be blank")
        if self.execution_authority:
            raise ValueError("reputation snapshots cannot grant execution authority")
        roles = [state.role for state in self.states]
        if len(roles) != len(set(roles)):
            raise ValueError("reputation snapshot roles must be unique")
        if len(self.processed_evidence_ids) != len(set(self.processed_evidence_ids)):
            raise ValueError("processed evidence ids must be unique")

    def state_for(self, role: str) -> RoleReputation | None:
        for state in self.states:
            if state.role == role:
                return state
        return None


def empty_reputation_snapshot(*, snapshot_id: str) -> ReputationSnapshot:
    return ReputationSnapshot(
        snapshot_id=snapshot_id,
        parent_snapshot_id=None,
        states=(),
        execution_authority=False,
    )


def apply_reputation_evidence(
    snapshot: ReputationSnapshot,
    *,
    next_snapshot_id: str,
    evidence: ReputationEvidence,
    policy: ReputationPolicy | None = None,
) -> ReputationSnapshot:
    """Apply one accepted, bounded validation observation idempotently.

    Oversized deltas are rejected rather than silently clamped. The aggregate
    score itself is bounded to ``[-max_abs_score, +max_abs_score]``.
    """
    config = policy or ReputationPolicy()
    if evidence.evidence_id in snapshot.processed_evidence_ids:
        return snapshot
    if not evidence.accepted:
        raise ValueError("reputation update requires explicitly accepted evidence")
    if evidence.sample_count < config.minimum_sample_count:
        raise ValueError("reputation update sample_count is below policy minimum")
    if abs(float(evidence.score_delta)) > config.max_abs_update:
        raise ValueError("reputation score_delta exceeds bounded update policy")

    existing = snapshot.state_for(evidence.role)
    if existing is None:
        existing = RoleReputation(
            role=evidence.role,
            objective=evidence.objective,
        )

    raw_score = existing.score + float(evidence.score_delta)
    bounded_score = max(-config.max_abs_score, min(config.max_abs_score, raw_score))
    updated = replace(
        existing,
        score=round(bounded_score, 12),
        update_count=existing.update_count + 1,
    )

    states = tuple(state for state in snapshot.states if state.role != evidence.role) + (updated,)
    states = tuple(sorted(states, key=lambda state: state.role))
    return ReputationSnapshot(
        snapshot_id=next_snapshot_id,
        parent_snapshot_id=snapshot.snapshot_id,
        states=states,
        processed_evidence_ids=snapshot.processed_evidence_ids + (evidence.evidence_id,),
        execution_authority=False,
    )


def rollback_reputation_snapshot(
    current: ReputationSnapshot,
    *,
    target: ReputationSnapshot,
    next_snapshot_id: str,
) -> ReputationSnapshot:
    """Create an immutable rollback snapshot while retaining evidence history."""
    if current.snapshot_id == target.snapshot_id:
        raise ValueError("rollback target must differ from current snapshot")

    processed = tuple(dict.fromkeys(current.processed_evidence_ids + target.processed_evidence_ids))
    return ReputationSnapshot(
        snapshot_id=next_snapshot_id,
        parent_snapshot_id=current.snapshot_id,
        states=target.states,
        processed_evidence_ids=processed,
        rollback_of_snapshot_id=target.snapshot_id,
        execution_authority=False,
    )


__all__ = [
    "ReputationEvidence",
    "ReputationPolicy",
    "ReputationSnapshot",
    "RoleReputation",
    "apply_reputation_evidence",
    "empty_reputation_snapshot",
    "rollback_reputation_snapshot",
]
