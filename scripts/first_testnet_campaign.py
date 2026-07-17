#!/usr/bin/env python3
"""Run one bounded real Testnet campaign to terminal evidence or a hard limit.

This operator runner never changes environment variables, credentials, Compose
configuration, the kill switch or Mainnet availability. It only calls canonical
campaign services and writes an append-only local evidence bundle.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.testnet_campaignctl import (  # noqa: E402
    CYCLE_CONFIRMATION,
    REPORT_CONFIRMATION,
    START_CONFIRMATION,
    CampaignControlServices,
    build_services,
)

_TERMINAL = {"completed", "blocked", "cancelled"}


def run(
    args: argparse.Namespace,
    services: CampaignControlServices,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    _require(args.start_confirmation, START_CONFIRMATION, "start")
    _require(args.cycle_confirmation, CYCLE_CONFIRMATION, "cycle")
    _require(args.report_confirmation, REPORT_CONFIRMATION, "report")

    plan = services.operations.first_testnet_plan(
        experiment_id=str(args.experiment_id),
        confirmation=str(args.start_confirmation),
    )
    bundle_root = Path(args.output_dir)
    bundle_root.mkdir(parents=True, exist_ok=True)
    _write_json(bundle_root / "launch-plan.json", plan)

    if args.resume_campaign_id:
        campaign = services.campaign.get(str(args.resume_campaign_id))
        if campaign is None:
            raise KeyError(str(args.resume_campaign_id))
        if str(campaign.get("experiment_id") or "") != str(args.experiment_id):
            raise ValueError("resume campaign experiment_id does not match")
        blockers = set(str(value) for value in plan.get("blockers") or [])
        if str(campaign.get("status")) not in _TERMINAL and blockers - {"no_active_campaign"}:
            return {
                "status": "blocked",
                "reason": "resume_plan_blocked",
                "blockers": sorted(blockers),
                "campaign_id": str(campaign.get("campaign_id") or ""),
                "evidence_dir": str(bundle_root),
                "real_fill_evidence_confirmed": False,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
    else:
        if not bool(plan.get("can_start")):
            return {
                "status": "blocked",
                "reason": "launch_plan_blocked",
                "blockers": list(plan.get("blockers") or []),
                "evidence_dir": str(bundle_root),
                "real_fill_evidence_confirmed": False,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
        started = services.operations.start_first_testnet_campaign(
            experiment_id=str(args.experiment_id),
            scope=str(args.scope),
            actor=str(args.actor),
            confirmation=str(args.start_confirmation),
        )
        campaign = dict(started["campaign"])

    campaign_id = str(campaign["campaign_id"])
    evidence_dir = bundle_root / campaign_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_json(evidence_dir / "campaign-start.json", campaign)
    cycles_file = evidence_dir / "cycles.jsonl"
    deadline = monotonic() + int(args.timeout_seconds)
    cycle_count = 0

    while str(campaign.get("status")) not in _TERMINAL:
        if cycle_count >= int(args.max_cycles):
            break
        if monotonic() >= deadline:
            break
        campaign = services.campaign.run_cycle(campaign_id, actor=str(args.actor))
        cycle_count += 1
        _append_jsonl(cycles_file, campaign)
        _write_json(evidence_dir / "campaign-latest.json", campaign)
        if str(campaign.get("status")) in _TERMINAL:
            break
        sleep(float(args.interval_seconds))

    report: dict[str, Any] = {}
    if str(campaign.get("status")) == "completed":
        report = services.reports.generate(campaign_id, actor=str(args.actor))
        _write_json(evidence_dir / "final-promotion-report.json", report)

    snapshot = services.operations.snapshot()
    _write_json(evidence_dir / "operations-final.json", snapshot)
    result = _final_result(campaign, report, evidence_dir, cycle_count)
    _write_json(evidence_dir / "runner-result.json", result)
    return result


def _final_result(
    campaign: Mapping[str, Any],
    report: Mapping[str, Any],
    evidence_dir: Path,
    cycle_count: int,
) -> dict[str, Any]:
    metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
    matched = int(metrics.get("matched_fill_count") or 0)
    actual_fees = bool(metrics.get("actual_execution_fees"))
    clean_identity = all(
        int(metrics.get(name) or 0) == 0
        for name in (
            "unmatched_paper_count",
            "unmatched_testnet_count",
            "orphan_execution_count",
            "duplicate_order_count",
            "unresolved_order_count",
        )
    )
    report_eligible = bool(report.get("eligible_for_manual_decision"))
    confirmed = bool(
        str(campaign.get("status")) == "completed"
        and matched >= 20
        and actual_fees
        and clean_identity
        and report_eligible
    )
    reason = "terminal"
    if str(campaign.get("status")) not in _TERMINAL:
        reason = "runner_limit_reached"
    elif str(campaign.get("status")) == "blocked":
        reason = "campaign_hard_blocked"
    return {
        "status": str(campaign.get("status") or "unknown"),
        "reason": reason,
        "campaign_id": str(campaign.get("campaign_id") or ""),
        "experiment_id": str(campaign.get("experiment_id") or ""),
        "scope": str(campaign.get("scope") or ""),
        "cycles_run_by_runner": cycle_count,
        "matched_fill_count": matched,
        "actual_execution_fees": actual_fees,
        "zero_identity_errors": clean_identity,
        "failed_gates": list(campaign.get("failed_gates") or []),
        "final_report_id": str(report.get("report_id") or campaign.get("final_report_id") or ""),
        "eligible_for_manual_decision": report_eligible,
        "real_fill_evidence_confirmed": confirmed,
        "evidence_dir": str(evidence_dir),
        "runtime_flags_changed": False,
        "mainnet_enabled": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--experiment-id", required=True)
    root.add_argument("--scope", default="BTCUSDT")
    root.add_argument("--actor", required=True)
    root.add_argument("--resume-campaign-id", default="")
    root.add_argument("--max-cycles", type=int, default=240)
    root.add_argument("--interval-seconds", type=float, default=15.0)
    root.add_argument("--timeout-seconds", type=int, default=14_400)
    root.add_argument("--output-dir", default="artifacts/testnet-campaigns")
    root.add_argument("--start-confirmation", required=True)
    root.add_argument("--cycle-confirmation", required=True)
    root.add_argument("--report-confirmation", required=True)
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
    if args.max_cycles < 1 or args.max_cycles > 10_000:
        print(json.dumps({"status": "blocked", "error": "max_cycles must be within 1..10000"}), file=errors)
        return 2
    if args.interval_seconds < 1 or args.interval_seconds > 300:
        print(json.dumps({"status": "blocked", "error": "interval_seconds must be within 1..300"}), file=errors)
        return 2
    if args.timeout_seconds < 60 or args.timeout_seconds > 86_400:
        print(json.dumps({"status": "blocked", "error": "timeout_seconds must be within 60..86400"}), file=errors)
        return 2
    try:
        result = run(args, services or build_services())
    except (KeyError, RuntimeError, TypeError, ValueError, OSError) as exc:
        result = {
            "status": "blocked",
            "error": f"{type(exc).__name__}: {exc}",
            "real_fill_evidence_confirmed": False,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), file=errors)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), file=output)
    return 0 if result.get("real_fill_evidence_confirmed") else 2


def _require(actual: str, expected: str, action: str) -> None:
    if str(actual) != expected:
        raise ValueError(f"{action} requires exact confirmation: {expected}")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


if __name__ == "__main__":
    raise SystemExit(main())
