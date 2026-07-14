from __future__ import annotations

import pytest

from campaigns import ScheduledCampaignOrchestrator, ShadowCampaignPolicy
from experiments import ExperimentRegistry
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def _completed_experiment(registry: ExperimentRegistry, experiment_id: str) -> dict:
    created = registry.create(
        experiment_id=experiment_id,
        commit_sha="abcdef1",
        manifest={
            "manifest_id": "btc-1m",
            "version": "1",
            "validated": True,
        },
        strategy_name="candidate",
        strategy_config={"lookback": 20},
        backtest_config={"fee_rate": 0.001},
    )
    running = registry.record_result(
        experiment_id,
        "walk_forward",
        {"net_pnl": 10.0},
        actor="test",
        expected_version=created["version"],
    )
    return registry.complete(
        experiment_id,
        actor="test",
        expected_version=running["version"],
    )


def _approve_testnet(registry: ExperimentRegistry, experiment_id: str) -> dict:
    completed = _completed_experiment(registry, experiment_id)
    pending = registry.save_promotion_report(
        experiment_id,
        {
            "target_stage": "testnet",
            "automated_gate_passed": True,
            "eligible_for_manual_approval": True,
            "failed_gates": [],
        },
        actor="test",
        expected_version=completed["version"],
    )
    return registry.manual_decision(
        experiment_id,
        target_stage="testnet",
        approve=True,
        actor="owner",
        reason="approved bounded Testnet evidence campaign",
        approval_token=f"APPROVE:{experiment_id}:testnet",
        expected_version=pending["version"],
    )


class _FakeCampaign:
    def __init__(self) -> None:
        self.started: list[dict] = []
        self.cycles: list[str] = []

    def start(self, **kwargs):
        self.started.append(dict(kwargs))
        return {
            "campaign_id": "campaign-1",
            "experiment_id": kwargs["experiment_id"],
            "scope": kwargs["scope"],
            "status": "scheduled",
        }

    def run_cycle(self, campaign_id: str, **kwargs):
        self.cycles.append(campaign_id)
        return {"campaign_id": campaign_id, "status": "running", **kwargs}

    def list(self, *, limit: int):
        return []


class _ActiveCampaign(_FakeCampaign):
    def __init__(self) -> None:
        super().__init__()
        self.active = {
            "campaign_id": "campaign-existing",
            "experiment_id": "exp-existing",
            "scope": "spot:testnet",
            "status": "running",
        }

    def list(self, *, limit: int):
        return [dict(self.active)]

    def run_cycle(self, campaign_id: str, **kwargs):
        self.cycles.append(campaign_id)
        return dict(self.active)


def test_scheduler_rejects_experiment_without_manual_testnet_approval(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ExperimentRegistry(database)
    _completed_experiment(registry, "exp-unapproved")
    orchestrator = ScheduledCampaignOrchestrator(database, campaign=_FakeCampaign())

    with pytest.raises(ValueError, match="promoted experiment"):
        orchestrator.create_schedule(
            experiment_id="exp-unapproved",
            scope="spot:testnet",
            interval_seconds=300,
            actor="owner",
            start_at_ms=1_000_000,
        )


def test_due_schedule_launches_once_and_advances_next_run(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ExperimentRegistry(database)
    _approve_testnet(registry, "exp-approved")
    campaign = _FakeCampaign()
    orchestrator = ScheduledCampaignOrchestrator(database, campaign=campaign)
    schedule = orchestrator.create_schedule(
        experiment_id="exp-approved",
        scope="spot:testnet",
        interval_seconds=300,
        actor="owner",
        start_at_ms=1_000_000,
    )

    result = orchestrator.tick(now_ms=1_000_000)

    assert result["status"] == "ok"
    assert result["launched_campaign_ids"] == ["campaign-1"]
    assert campaign.cycles == ["campaign-1"]
    updated = orchestrator.list_schedules()[0]
    assert updated["schedule_id"] == schedule["schedule_id"]
    assert updated["run_count"] == 1
    assert updated["last_campaign_id"] == "campaign-1"
    assert updated["next_run_at_ms"] == 1_300_000
    assert updated["runtime_flags_changed"] is False

    second = orchestrator.tick(now_ms=1_100_000)
    assert second["launched_campaign_ids"] == []
    assert len(campaign.started) == 1


def test_scheduler_defers_due_schedule_while_global_campaign_is_running(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ExperimentRegistry(database)
    _approve_testnet(registry, "exp-approved")
    campaign = _ActiveCampaign()
    orchestrator = ScheduledCampaignOrchestrator(database, campaign=campaign)
    schedule = orchestrator.create_schedule(
        experiment_id="exp-approved",
        scope="spot:testnet",
        interval_seconds=300,
        actor="owner",
        start_at_ms=1_000_000,
    )

    result = orchestrator.tick(now_ms=1_000_000)

    assert result["launched_campaign_ids"] == []
    assert result["deferred_schedule_ids"] == [schedule["schedule_id"]]
    assert campaign.started == []
    assert campaign.cycles == ["campaign-existing"]
    updated = orchestrator.list_schedules()[0]
    assert updated["status"] == "deferred"
    assert updated["last_deferred_reason"] == "global_campaign_authorization_busy"
    assert updated["next_run_at_ms"] == 1_300_000


def test_shadow_campaign_policy_cannot_relax_hard_bounds() -> None:
    with pytest.raises(ValueError, match="10..25"):
        ShadowCampaignPolicy(minimum_testnet_notional_usdt=9.99)
    with pytest.raises(ValueError, match="minimum..25"):
        ShadowCampaignPolicy(maximum_testnet_notional_usdt=25.01)
    with pytest.raises(ValueError, match="at least 20"):
        ShadowCampaignPolicy(minimum_matched_fills=19)
