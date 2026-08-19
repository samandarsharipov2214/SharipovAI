from __future__ import annotations

import pytest

from autonomous_trading.learning_reputation_v2 import (
    ReputationEvidence,
    ReputationPolicy,
    apply_reputation_evidence,
    empty_reputation_snapshot,
    rollback_reputation_snapshot,
)
from autonomous_trading.role_aware_learning_v2 import LearningObjective


def _evidence(
    *,
    evidence_id: str,
    role: str = "market_intelligence",
    objective: LearningObjective = LearningObjective.DIRECTIONAL_QUALITY,
    score_delta: float = 0.04,
    sample_count: int = 25,
    accepted: bool = True,
) -> ReputationEvidence:
    return ReputationEvidence(
        evidence_id=evidence_id,
        role=role,
        objective=objective,
        score_delta=score_delta,
        sample_count=sample_count,
        validation_protocol_id="reputation-protocol-v1",
        accepted=accepted,
    )


def test_reputation_update_is_bounded_idempotent_and_non_executing() -> None:
    initial = empty_reputation_snapshot(snapshot_id="rep-0")
    updated = apply_reputation_evidence(
        initial,
        next_snapshot_id="rep-1",
        evidence=_evidence(evidence_id="ev-1"),
    )

    state = updated.state_for("market_intelligence")
    assert state is not None
    assert state.score == 0.04
    assert state.update_count == 1
    assert updated.parent_snapshot_id == "rep-0"
    assert updated.processed_evidence_ids == ("ev-1",)
    assert updated.execution_authority is False

    duplicate = apply_reputation_evidence(
        updated,
        next_snapshot_id="rep-2",
        evidence=_evidence(evidence_id="ev-1"),
    )
    assert duplicate is updated


def test_reputation_rejects_unaccepted_small_sample_and_oversized_updates() -> None:
    snapshot = empty_reputation_snapshot(snapshot_id="rep-0")

    with pytest.raises(ValueError, match="explicitly accepted"):
        apply_reputation_evidence(
            snapshot,
            next_snapshot_id="rep-rejected",
            evidence=_evidence(evidence_id="ev-rejected", accepted=False),
        )

    with pytest.raises(ValueError, match="below policy minimum"):
        apply_reputation_evidence(
            snapshot,
            next_snapshot_id="rep-small",
            evidence=_evidence(evidence_id="ev-small", sample_count=5),
        )

    with pytest.raises(ValueError, match="exceeds bounded update"):
        apply_reputation_evidence(
            snapshot,
            next_snapshot_id="rep-large",
            evidence=_evidence(evidence_id="ev-large", score_delta=0.2),
        )


def test_role_objective_contract_prevents_veto_role_directional_reputation() -> None:
    with pytest.raises(ValueError, match="canonical role objective"):
        _evidence(
            evidence_id="ev-risk-wrong-objective",
            role="risk_engine",
            objective=LearningObjective.DIRECTIONAL_QUALITY,
        )

    risk_evidence = _evidence(
        evidence_id="ev-risk",
        role="risk_engine",
        objective=LearningObjective.VETO_QUALITY,
        score_delta=0.03,
    )
    updated = apply_reputation_evidence(
        empty_reputation_snapshot(snapshot_id="rep-0"),
        next_snapshot_id="rep-risk",
        evidence=risk_evidence,
    )
    state = updated.state_for("risk_engine")
    assert state is not None
    assert state.objective is LearningObjective.VETO_QUALITY
    assert state.score == 0.03


def test_score_is_bounded_and_rollback_restores_state_without_erasing_audit_history() -> None:
    policy = ReputationPolicy(max_abs_score=0.1, max_abs_update=0.05, minimum_sample_count=20)
    initial = empty_reputation_snapshot(snapshot_id="rep-0")
    first = apply_reputation_evidence(
        initial,
        next_snapshot_id="rep-1",
        evidence=_evidence(evidence_id="ev-1", score_delta=0.05),
        policy=policy,
    )
    second = apply_reputation_evidence(
        first,
        next_snapshot_id="rep-2",
        evidence=_evidence(evidence_id="ev-2", score_delta=0.05),
        policy=policy,
    )
    third = apply_reputation_evidence(
        second,
        next_snapshot_id="rep-3",
        evidence=_evidence(evidence_id="ev-3", score_delta=0.05),
        policy=policy,
    )

    state = third.state_for("market_intelligence")
    assert state is not None
    assert state.score == 0.1
    assert state.update_count == 3

    rolled_back = rollback_reputation_snapshot(
        third,
        target=first,
        next_snapshot_id="rep-rollback",
    )
    rollback_state = rolled_back.state_for("market_intelligence")
    assert rollback_state is not None
    assert rollback_state.score == 0.05
    assert rollback_state.update_count == 1
    assert rolled_back.parent_snapshot_id == "rep-3"
    assert rolled_back.rollback_of_snapshot_id == "rep-1"
    assert rolled_back.processed_evidence_ids == ("ev-1", "ev-2", "ev-3")
    assert rolled_back.execution_authority is False

    # Rolled-back evidence remains processed and cannot be double-applied.
    duplicate_after_rollback = apply_reputation_evidence(
        rolled_back,
        next_snapshot_id="rep-duplicate",
        evidence=_evidence(evidence_id="ev-2", score_delta=0.05),
        policy=policy,
    )
    assert duplicate_after_rollback is rolled_back


def test_snapshot_rejects_same_target_rollback() -> None:
    snapshot = empty_reputation_snapshot(snapshot_id="rep-0")
    with pytest.raises(ValueError, match="must differ"):
        rollback_reputation_snapshot(
            snapshot,
            target=snapshot,
            next_snapshot_id="rep-rollback",
        )
