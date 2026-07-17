from __future__ import annotations

import io
import json
from types import SimpleNamespace

from scripts.testnet_campaignctl import (
    CYCLE_CONFIRMATION,
    DECISION_CONFIRMATION,
    REPORT_CONFIRMATION,
    CampaignControlServices,
    FIRST_TESTNET_CONFIRMATION,
    main,
)


class _Operations:
    def __init__(self) -> None:
        self.started: list[dict] = []

    def snapshot(self):
        return {"status": "ok", "mainnet_enabled": False}

    def first_testnet_plan(self, *, experiment_id: str, confirmation: str):
        ready = experiment_id == "exp-ready" and confirmation == FIRST_TESTNET_CONFIRMATION
        return {
            "status": "ready" if ready else "blocked",
            "can_start": ready,
            "blockers": [] if ready else ["approved_promoted_experiment"],
            "mainnet_enabled": False,
        }

    def start_first_testnet_campaign(self, **kwargs):
        self.started.append(dict(kwargs))
        return {
            "status": "started",
            "campaign": {"campaign_id": "campaign-1", "status": "running"},
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }


class _Campaign:
    def __init__(self) -> None:
        self.cycles: list[dict] = []

    def run_cycle(self, campaign_id: str, *, actor: str):
        self.cycles.append({"campaign_id": campaign_id, "actor": actor})
        return {"campaign_id": campaign_id, "status": "running"}


class _Reports:
    def __init__(self) -> None:
        self.generated: list[dict] = []

    def generate(self, campaign_id: str, *, actor: str):
        self.generated.append({"campaign_id": campaign_id, "actor": actor})
        return {
            "report_id": "promotion-1",
            "campaign_id": campaign_id,
            "status": "eligible_for_manual_decision",
        }


class _Decisions:
    def __init__(self) -> None:
        self.decisions: list[dict] = []

    def snapshot(self, campaign_id: str):
        return {
            "campaign_id": campaign_id,
            "status": "awaiting_manual_decision",
        }

    def decide(self, campaign_id: str, **kwargs):
        payload = {"campaign_id": campaign_id, **kwargs}
        self.decisions.append(payload)
        return {
            "decision_id": "decision-1",
            "campaign_id": campaign_id,
            "approved": bool(kwargs["approve"]),
            "status": "approved" if kwargs["approve"] else "rejected",
        }


def _services() -> CampaignControlServices:
    return CampaignControlServices(
        operations=_Operations(),
        campaign=_Campaign(),
        reports=_Reports(),
        decisions=_Decisions(),
    )


def _run(argv: list[str], services: CampaignControlServices):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv, services=services, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_plan_returns_nonzero_until_all_gates_and_exact_confirmation_pass() -> None:
    services = _services()

    code, stdout, stderr = _run(
        ["plan", "--experiment-id", "missing"],
        services,
    )

    assert code == 2
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "blocked"
    assert payload["can_start"] is False
    assert payload["mainnet_enabled"] is False


def test_start_requires_action_bound_confirmation_before_service_call() -> None:
    services = _services()

    code, stdout, stderr = _run(
        [
            "start",
            "--experiment-id",
            "exp-ready",
            "--scope",
            "BTCUSDT",
            "--actor",
            "owner",
            "--confirmation",
            "wrong",
        ],
        services,
    )

    assert code == 2
    assert stdout == ""
    assert "requires exact confirmation" in stderr
    assert services.operations.started == []


def test_start_uses_canonical_operations_service_without_runtime_mutation() -> None:
    services = _services()

    code, stdout, stderr = _run(
        [
            "start",
            "--experiment-id",
            "exp-ready",
            "--scope",
            "BTCUSDT",
            "--actor",
            "owner",
            "--confirmation",
            FIRST_TESTNET_CONFIRMATION,
        ],
        services,
    )

    assert code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "started"
    assert payload["runtime_flags_changed"] is False
    assert payload["mainnet_enabled"] is False
    assert services.operations.started == [
        {
            "experiment_id": "exp-ready",
            "scope": "BTCUSDT",
            "actor": "owner",
            "confirmation": FIRST_TESTNET_CONFIRMATION,
        }
    ]


def test_cycle_report_and_decision_each_require_distinct_confirmation() -> None:
    services = _services()

    cycle_code, cycle_stdout, _ = _run(
        [
            "cycle",
            "--campaign-id",
            "campaign-1",
            "--actor",
            "owner",
            "--confirmation",
            CYCLE_CONFIRMATION,
        ],
        services,
    )
    report_code, report_stdout, _ = _run(
        [
            "report",
            "--campaign-id",
            "campaign-1",
            "--actor",
            "owner",
            "--confirmation",
            REPORT_CONFIRMATION,
        ],
        services,
    )
    decision_code, decision_stdout, _ = _run(
        [
            "decision",
            "--campaign-id",
            "campaign-1",
            "--action",
            "approve",
            "--reason",
            "all immutable campaign gates are green",
            "--approval-token",
            "CAMPAIGN_DECISION:campaign-1:promotion-1:APPROVE",
            "--actor",
            "owner",
            "--confirmation",
            DECISION_CONFIRMATION,
        ],
        services,
    )

    assert cycle_code == report_code == decision_code == 0
    assert json.loads(cycle_stdout)["mainnet_enabled"] is False
    assert json.loads(report_stdout)["mainnet_enabled"] is False
    decision = json.loads(decision_stdout)
    assert decision["manual_decision_only"] is True
    assert decision["runtime_flags_changed"] is False
    assert decision["runtime_deployment_changed"] is False
    assert decision["mainnet_enabled"] is False
