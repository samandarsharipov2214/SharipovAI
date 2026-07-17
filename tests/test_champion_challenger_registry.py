from __future__ import annotations

import pytest

from experiments import ChampionChallengerRegistry, ExperimentRegistry
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")


def _promoted_experiment(registry: ExperimentRegistry, experiment_id: str):
    current = registry.create(
        experiment_id=experiment_id,
        commit_sha="d28de813188e93603fe3384ebe3926d97fb916a3",
        manifest={
            "manifest_id": "btc-data",
            "version": "v1",
            "sha256": "a" * 64,
            "validated": True,
        },
        strategy_name=experiment_id,
        strategy_config={},
        backtest_config={},
    )
    current = registry.record_result(
        experiment_id,
        "walk_forward",
        {"net_pnl": 100.0},
        actor="runner",
        expected_version=current["version"],
    )
    current = registry.complete(
        experiment_id,
        actor="runner",
        expected_version=current["version"],
    )
    current = registry.save_promotion_report(
        experiment_id,
        {
            "experiment_id": experiment_id,
            "target_stage": "paper",
            "status": "eligible_for_manual_approval",
            "automated_gate_passed": True,
            "eligible_for_manual_approval": True,
            "manual_approval_required": True,
            "passed_gates": ["all"],
            "failed_gates": [],
            "warnings": [],
            "metrics": {},
            "policy": {},
        },
        actor="controller",
        expected_version=current["version"],
    )
    return registry.manual_decision(
        experiment_id,
        target_stage="paper",
        approve=True,
        actor="owner",
        reason="Reviewed immutable evidence",
        approval_token=f"APPROVE:{experiment_id}:paper",
        expected_version=current["version"],
    )


def test_only_evidence_approved_challenger_can_become_champion(tmp_path) -> None:
    database = _database(tmp_path)
    experiments = ExperimentRegistry(database)
    _promoted_experiment(experiments, "exp-challenger-1")
    leadership = ChampionChallengerRegistry(database, experiments=experiments)

    state = leadership.register_challenger(
        "spot-btc",
        "exp-challenger-1",
        actor="general-controller",
        reason="Candidate passed research promotion",
        expected_version=0,
    )
    promoted = leadership.promote_challenger(
        "spot-btc",
        "exp-challenger-1",
        target_stage="paper",
        actor="owner",
        reason="Champion selected after evidence review",
        approval_token="PROMOTE:spot-btc:exp-challenger-1:paper",
        expected_version=state["version"],
    )

    assert promoted["champion_experiment_id"] == "exp-challenger-1"
    assert promoted["runtime_deployment_changed"] is False
    assert promoted["last_decision"]["evidence_sha256"]


def test_unapproved_experiment_cannot_become_champion(tmp_path) -> None:
    database = _database(tmp_path)
    experiments = ExperimentRegistry(database)
    current = experiments.create(
        experiment_id="exp-unapproved",
        commit_sha="d28de813",
        manifest={"manifest_id": "btc", "version": "v1", "sha256": "b" * 64, "validated": True},
        strategy_name="candidate",
        strategy_config={},
        backtest_config={},
    )
    current = experiments.record_result(
        "exp-unapproved",
        "walk_forward",
        {"net_pnl": 1.0},
        actor="runner",
        expected_version=current["version"],
    )
    experiments.complete(
        "exp-unapproved",
        actor="runner",
        expected_version=current["version"],
    )
    leadership = ChampionChallengerRegistry(database, experiments=experiments)
    state = leadership.register_challenger(
        "spot-btc",
        "exp-unapproved",
        actor="controller",
        reason="Research candidate",
        expected_version=0,
    )

    with pytest.raises(ValueError, match="promoted experiment"):
        leadership.promote_challenger(
            "spot-btc",
            "exp-unapproved",
            target_stage="paper",
            actor="owner",
            reason="Not actually approved",
            approval_token="PROMOTE:spot-btc:exp-unapproved:paper",
            expected_version=state["version"],
        )
