from __future__ import annotations

from types import SimpleNamespace

import pytest

from campaigns.operations import CampaignOperationsService, FIRST_TESTNET_CONFIRMATION
from storage import ProjectDatabase


class _ExecutionClient:
    def status(self):
        return {
            "mode": "sandbox",
            "credentials_configured": False,
            "testnet_execution_enabled": False,
            "kill_switch": True,
            "mainnet_execution_compiled": False,
            "mainnet_hard_blocked": True,
            "restart_safe": True,
        }


class _PrivateStream:
    def evaluate(self, *, required: bool, now_ms: int):
        assert required is True
        assert now_ms > 0
        return SimpleNamespace(to_dict=lambda: {"ready": False, "status": "blocked"})


class _Executions:
    def snapshot(self):
        return {
            "managed_orders": [
                {"order_link_id": "sai_fee", "actual_fee": 0.0125},
                {"order_link_id": "sai_foreign", "actual_fee": 99.0},
            ]
        }


class _Campaign:
    policy = SimpleNamespace(
        minimum_testnet_notional_usdt=10.0,
        maximum_testnet_notional_usdt=25.0,
        minimum_matched_fills=20,
        maximum_orphan_orders=0,
        maximum_duplicate_orders=0,
        maximum_unresolved_orders=0,
    )

    def __init__(self):
        self.bridge = SimpleNamespace(client=_ExecutionClient())
        self.private_stream = _PrivateStream()
        self.executions = _Executions()
        self.started = []
        self.records = [{"order_link_id": "sai_fee"}]

    def list(self, *, limit: int):
        assert limit > 0
        return [
            {
                "campaign_id": "campaign_phase6",
                "experiment_id": "experiment_phase6",
                "scope": "BTCUSDT",
                "status": "running",
                "cycle_count": 3,
                "policy": {"minimum_matched_fills": 20},
                "metrics": {
                    "matched_fill_count": 8,
                    "orphan_execution_count": 0,
                    "duplicate_order_count": 0,
                    "unresolved_order_count": 0,
                    "actual_execution_fees": True,
                },
                "failed_gates": ["minimum_20_matched_fills_pending"],
                "final_report_id": "",
            }
        ]

    def _campaign_records(self, campaign_id: str):
        assert campaign_id
        return list(self.records)

    def start(self, **kwargs):
        self.started.append(kwargs)
        return {"campaign_id": "campaign_started", "status": "scheduled", **kwargs}

    def run_cycle(self, campaign_id: str, **kwargs):
        return {
            "campaign_id": campaign_id,
            "experiment_id": "experiment_phase6",
            "scope": "BTCUSDT",
            "status": "running",
            "policy": {"minimum_matched_fills": 20},
            "metrics": {},
            "failed_gates": ["minimum_20_matched_fills_pending"],
            **kwargs,
        }


class _Orchestrator:
    def __init__(self, campaign):
        self.campaign = campaign

    def list_schedules(self, *, limit: int):
        return [
            {
                "schedule_id": "schedule_phase6",
                "experiment_id": "experiment_phase6",
                "scope": "BTCUSDT",
                "status": "scheduled",
                "next_run_at_ms": 1_800_000_000_000,
                "run_count": 0,
            }
        ]

    def status(self):
        return {
            "enabled": False,
            "worker_running": False,
            "single_global_campaign_authorization": True,
        }


class _Reports:
    def list(self, *, limit: int):
        return []

    def get(self, report_id: str):
        return None


def _service(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'phase6.db'}")
    campaign = _Campaign()
    return CampaignOperationsService(
        database,
        orchestrator=_Orchestrator(campaign),
        campaign=campaign,
        reports=_Reports(),
    )


def test_operations_snapshot_exposes_fill_identity_fee_and_report_state(tmp_path) -> None:
    snapshot = _service(tmp_path).snapshot()
    active = snapshot["active_campaign"]
    assert snapshot["schedule_count"] == 1
    assert snapshot["active_campaign_count"] == 1
    assert active["progress"] == {
        "matched_fills": 8,
        "target_fills": 20,
        "percent": 40.0,
        "remaining_fills": 12,
    }
    assert active["identity_integrity"]["zero_identity_errors"] is True
    assert active["fees"]["actual_execution_fees"] is True
    assert active["fees"]["actual_fee_total"] == pytest.approx(0.0125)
    assert active["final_report"]["ready"] is False
    assert snapshot["mainnet_enabled"] is False
    assert snapshot["runtime_flags_changed"] is False


def test_fee_total_is_zero_without_campaign_bound_order_links(tmp_path) -> None:
    service = _service(tmp_path)
    service.campaign.records = []
    snapshot = service.snapshot()
    assert snapshot["active_campaign"]["fees"]["actual_fee_total"] == 0.0


def test_first_campaign_plan_is_blocked_without_explicit_runtime_release(tmp_path, monkeypatch) -> None:
    for name in (
        "PHASE6_TESTNET_RELEASE_GATE",
        "TESTNET_EXECUTION_ENABLED",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        "AUTONOMOUS_TESTNET_ENABLED",
        "FEATURE_BYBIT_PRIVATE_ORDER_WS",
        "RUNTIME_FILL_HARVESTER_ENABLED",
        "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    plan = _service(tmp_path).first_testnet_plan(
        experiment_id="missing",
        confirmation=FIRST_TESTNET_CONFIRMATION,
    )
    assert plan["can_start"] is False
    assert "release_gate_green" in plan["blockers"]
    assert "testnet_credentials_configured" in plan["blockers"]
    assert "private_stream_ready" in plan["blockers"]
    assert plan["mainnet_enabled"] is False


def test_start_never_bypasses_failed_gates(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(RuntimeError, match="blocked"):
        service.start_first_testnet_campaign(
            experiment_id="experiment_phase6",
            scope="BTCUSDT",
            actor="admin",
            confirmation=FIRST_TESTNET_CONFIRMATION,
        )
    assert service.campaign.started == []


def test_start_uses_existing_campaign_state_machine_after_all_gates(monkeypatch, tmp_path) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(service, "first_testnet_plan", lambda **_: {"can_start": True, "blockers": []})
    result = service.start_first_testnet_campaign(
        experiment_id="experiment_phase6",
        scope="BTCUSDT",
        actor="admin",
        confirmation=FIRST_TESTNET_CONFIRMATION,
        now_ms=1_800_000_000_000,
    )
    assert result["status"] == "started"
    assert result["campaign"]["campaign_id"] == "campaign_started"
    assert result["automatic_final_report"] is True
    assert result["manual_promotion_required"] is True
    assert result["mainnet_enabled"] is False
    assert result["runtime_flags_changed"] is False
    assert service.campaign.started[0]["schedule_id"] == "phase6-first-testnet"
