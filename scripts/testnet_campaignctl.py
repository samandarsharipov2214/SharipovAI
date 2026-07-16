"""Fail-closed operator CLI for the bounded Testnet campaign lifecycle.

The CLI is a thin adapter over the canonical campaign services. It cannot set
runtime flags, install credentials, disable the kill switch or enable Mainnet.
Write operations require exact action-bound confirmation phrases.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Sequence, TextIO

from campaigns import (
    CampaignOperationsService,
    CampaignPromotionDecisionEngine,
    FinalPromotionReportEngine,
    FIRST_TESTNET_CONFIRMATION,
    ScheduledCampaignOrchestrator,
    TestnetShadowCampaign,
)
from storage import ProjectDatabase

START_CONFIRMATION = "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN"
CYCLE_CONFIRMATION = "I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE"
REPORT_CONFIRMATION = "I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT"
DECISION_CONFIRMATION = "I_APPROVE_MANUAL_CAMPAIGN_DECISION"

if FIRST_TESTNET_CONFIRMATION != START_CONFIRMATION:
    raise RuntimeError("campaign CLI start confirmation diverged from canonical policy")


@dataclass(frozen=True, slots=True)
class CampaignControlServices:
    operations: CampaignOperationsService
    campaign: TestnetShadowCampaign
    reports: FinalPromotionReportEngine
    decisions: CampaignPromotionDecisionEngine


def build_services(database: ProjectDatabase | None = None) -> CampaignControlServices:
    db = database or ProjectDatabase()
    db.initialize()
    campaign = TestnetShadowCampaign(db)
    reports = FinalPromotionReportEngine(db)
    orchestrator = ScheduledCampaignOrchestrator(db, campaign=campaign)
    operations = CampaignOperationsService(
        db,
        orchestrator=orchestrator,
        campaign=campaign,
        reports=reports,
    )
    decisions = CampaignPromotionDecisionEngine(
        db,
        campaigns=campaign,
        reports=reports,
    )
    return CampaignControlServices(
        operations=operations,
        campaign=campaign,
        reports=reports,
        decisions=decisions,
    )


def execute(args: argparse.Namespace, services: CampaignControlServices) -> dict[str, Any]:
    command = str(args.command)
    if command == "snapshot":
        return services.operations.snapshot()

    if command == "plan":
        return services.operations.first_testnet_plan(
            experiment_id=str(args.experiment_id or ""),
            confirmation=str(args.confirmation or ""),
        )

    if command == "start":
        _require_confirmation(args.confirmation, START_CONFIRMATION, command)
        return services.operations.start_first_testnet_campaign(
            experiment_id=str(args.experiment_id),
            scope=str(args.scope),
            actor=str(args.actor),
            confirmation=str(args.confirmation),
        )

    if command == "cycle":
        _require_confirmation(args.confirmation, CYCLE_CONFIRMATION, command)
        campaign = services.campaign.run_cycle(
            str(args.campaign_id),
            actor=str(args.actor),
        )
        return {
            "status": "ok",
            "campaign": campaign,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    if command == "report":
        _require_confirmation(args.confirmation, REPORT_CONFIRMATION, command)
        report = services.reports.generate(
            str(args.campaign_id),
            actor=str(args.actor),
        )
        return {
            "status": "ok",
            "report": report,
            "manual_decision": services.decisions.snapshot(str(args.campaign_id)),
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    if command == "decision":
        _require_confirmation(args.confirmation, DECISION_CONFIRMATION, command)
        approve = str(args.action) == "approve"
        decision = services.decisions.decide(
            str(args.campaign_id),
            approve=approve,
            actor=str(args.actor),
            reason=str(args.reason),
            approval_token=str(args.approval_token),
        )
        return {
            "status": "ok",
            "decision": decision,
            "manual_decision_only": True,
            "runtime_flags_changed": False,
            "runtime_deployment_changed": False,
            "mainnet_enabled": False,
        }

    raise ValueError(f"unsupported command: {command}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    subparsers.add_parser("snapshot", help="read Campaign Operations state")

    plan = subparsers.add_parser("plan", help="evaluate all first-campaign gates")
    plan.add_argument("--experiment-id", default="")
    plan.add_argument("--confirmation", default="")

    start = subparsers.add_parser("start", help="start the first bounded campaign")
    _actor(start)
    start.add_argument("--experiment-id", required=True)
    start.add_argument("--scope", default="BTCUSDT")
    start.add_argument("--confirmation", required=True)

    cycle = subparsers.add_parser("cycle", help="run one canonical campaign cycle")
    _actor(cycle)
    cycle.add_argument("--campaign-id", required=True)
    cycle.add_argument("--confirmation", required=True)

    report = subparsers.add_parser("report", help="generate an immutable final report")
    _actor(report)
    report.add_argument("--campaign-id", required=True)
    report.add_argument("--confirmation", required=True)

    decision = subparsers.add_parser("decision", help="persist the manual final decision")
    _actor(decision)
    decision.add_argument("--campaign-id", required=True)
    decision.add_argument("--action", choices=("approve", "reject"), required=True)
    decision.add_argument("--reason", required=True)
    decision.add_argument("--approval-token", required=True)
    decision.add_argument("--confirmation", required=True)
    return root


def main(
    argv: Sequence[str] | None = None,
    *,
    services: CampaignControlServices | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    args = parser().parse_args(argv)
    try:
        result = execute(args, services or build_services())
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        payload = {
            "status": "blocked",
            "command": str(args.command),
            "error": f"{type(exc).__name__}: {exc}",
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), file=errors)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), file=output)
    if str(args.command) == "plan" and not bool(result.get("can_start")):
        return 2
    return 0


def _actor(command: argparse.ArgumentParser) -> None:
    command.add_argument("--actor", required=True)


def _require_confirmation(actual: str, expected: str, command: str) -> None:
    if str(actual) != expected:
        raise ValueError(f"{command} requires exact confirmation: {expected}")


if __name__ == "__main__":
    raise SystemExit(main())
