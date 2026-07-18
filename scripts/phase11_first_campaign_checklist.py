#!/usr/bin/env python3
"""Fail-closed readiness gate for the first real bounded Testnet campaign.

This command is read-only. It never changes runtime flags, starts a campaign,
submits an order, installs credentials, disables a kill switch or enables Mainnet.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from campaigns.phase10_scaling import ControlledScalingService
from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED
from scripts.testnet_campaignctl import START_CONFIRMATION, build_services

_REQUIRED_TRUE = (
    "TESTNET_EXECUTION_ENABLED",
    "AUTONOMOUS_TESTNET_ENABLED",
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    "FEATURE_BYBIT_TESTNET",
    "FEATURE_BYBIT_PRIVATE_ORDER_WS",
    "RUNTIME_FILL_HARVESTER_ENABLED",
)
_REQUIRED_FALSE = (
    "EXCHANGE_LIVE_TRADING_ENABLED",
    "FEATURE_BYBIT_LIVE_EXECUTION",
    "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS",
    "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED",
)


def evaluate_readiness(
    *,
    environ: Mapping[str, str],
    audit: Mapping[str, Any],
    current_sha: str,
    expected_sha: str,
    plan: Mapping[str, Any],
    active_scaling_authorities: int,
) -> dict[str, Any]:
    testnet_key = bool(str(environ.get("BYBIT_TESTNET_API_KEY", "")).strip())
    testnet_secret = bool(str(environ.get("BYBIT_TESTNET_API_SECRET", "")).strip())
    mainnet_key = bool(str(environ.get("BYBIT_MAINNET_API_KEY", "")).strip())
    mainnet_secret = bool(str(environ.get("BYBIT_MAINNET_API_SECRET", "")).strip())
    max_execution = _finite(environ.get("EXECUTION_MAX_NOTIONAL_USDT", ""))
    max_shadow = _finite(environ.get("SHADOW_TESTNET_MAX_NOTIONAL_USDT", ""))
    expected_sha_valid = _full_sha(expected_sha)
    current_sha_valid = _full_sha(current_sha)
    audit_blockers = list(audit.get("blockers") or [])
    plan_blockers = list(plan.get("blockers") or [])

    checks = {
        "expected_sha_is_full_commit": expected_sha_valid,
        "container_build_sha_is_full_commit": current_sha_valid,
        "deployed_sha_matches": expected_sha_valid
        and current_sha_valid
        and current_sha == expected_sha,
        "audit_sha_matches_deployment": str(audit.get("deployed_sha") or "")
        == expected_sha,
        "production_audit_ready": audit.get("status")
        == "ready_for_bounded_testnet_preflight"
        and not audit_blockers,
        "audit_mainnet_locked": audit.get("mainnet_enabled") is False,
        "mainnet_compile_lock": MAINNET_EXECUTION_COMPILED is False,
        "sandbox_exchange_mode": str(environ.get("EXCHANGE_MODE", "")).strip().lower()
        == "sandbox",
        "testnet_base_url": str(environ.get("EXCHANGE_BASE_URL", "")).strip().rstrip("/")
        == "https://api-testnet.bybit.com",
        "bounded_runtime_flags_enabled": all(
            _truthy(environ.get(name, "0")) for name in _REQUIRED_TRUE
        ),
        "live_legacy_and_scheduler_disabled": all(
            not _truthy(environ.get(name, "0")) for name in _REQUIRED_FALSE
        ),
        "finite_window_kill_switch_state": not _truthy(
            environ.get("EXECUTION_KILL_SWITCH", "1")
        ),
        "release_gate_green": str(
            environ.get("PHASE6_TESTNET_RELEASE_GATE", "")
        ).strip()
        == "green",
        "isolated_testnet_credentials_complete": testnet_key and testnet_secret,
        "mainnet_credentials_absent": not mainnet_key and not mainnet_secret,
        "execution_notional_bounded": max_execution is not None
        and 0 < max_execution <= 25,
        "shadow_notional_bounded": max_shadow is not None and 0 < max_shadow <= 25,
        "canonical_plan_ready": plan.get("status") == "ready"
        and plan.get("can_start") is True
        and not plan_blockers,
        "no_scaling_authority_before_first_campaign": active_scaling_authorities == 0,
        "automatic_campaign_launch_disabled": audit.get("automatic_campaign_launch")
        is False,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": 3,
        "status": "ready" if not failed else "blocked",
        "ready": not failed,
        "checked_at_ms": int(time.time() * 1000),
        "expected_sha": expected_sha,
        "deployed_sha": current_sha,
        "audit_sha256": str(audit.get("audit_sha256") or ""),
        "checks": checks,
        "failed_checks": failed,
        "audit_blockers": audit_blockers,
        "campaign_plan_blockers": plan_blockers,
        "active_scaling_authorities": int(active_scaling_authorities),
        "maximum_order_notional_usdt": 25,
        "minimum_matched_fills": 20,
        "actual_private_fills_required": True,
        "actual_fee_evidence_required": True,
        "manual_start_required": True,
        "scheduler_enabled": False,
        "runtime_flags_changed": False,
        "campaign_started": False,
        "mainnet_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--audit-file",
        default="/var/lib/sharipovai/audit/phase11-post-deploy.json",
    )
    parser.add_argument(
        "--expected-sha",
        default=os.getenv("SHARIPOVAI_EXPECTED_SHA", ""),
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    audit_path = Path(args.audit_file).expanduser().resolve()
    if not audit_path.is_file():
        report = _blocked("post_deploy_audit_missing", expected_sha=args.expected_sha)
        _emit(report, args.output)
        return 2
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report = _blocked(
            "post_deploy_audit_invalid",
            expected_sha=args.expected_sha,
            error_type=type(exc).__name__,
        )
        _emit(report, args.output)
        return 2
    if not isinstance(audit, dict):
        report = _blocked(
            "post_deploy_audit_not_object",
            expected_sha=args.expected_sha,
        )
        _emit(report, args.output)
        return 2

    try:
        current_sha = _runtime_build_sha(os.environ)
        services = build_services()
        plan = services.operations.first_testnet_plan(
            experiment_id=str(args.experiment_id),
            confirmation=START_CONFIRMATION,
        )
        scaling = ControlledScalingService(services.campaign.database)
        active_count = len(scaling.active_activations(limit=500))
        report = evaluate_readiness(
            environ=os.environ,
            audit=audit,
            current_sha=current_sha,
            expected_sha=str(args.expected_sha).strip().lower(),
            plan=plan,
            active_scaling_authorities=active_count,
        )
    except Exception as exc:
        report = _blocked(
            "checklist_internal_failure",
            expected_sha=args.expected_sha,
            error_type=type(exc).__name__,
        )
    _emit(report, args.output)
    return 0 if report.get("ready") is True else 2


def _runtime_build_sha(environ: Mapping[str, str]) -> str:
    embedded = str(environ.get("SHARIPOVAI_BUILD_SHA", "")).strip().lower()
    if _full_sha(embedded):
        return embedded
    try:
        candidate = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return ""
    return candidate if _full_sha(candidate) else ""


def _blocked(reason: str, *, expected_sha: str, error_type: str = "") -> dict[str, Any]:
    payload = {
        "schema_version": 3,
        "status": "blocked",
        "ready": False,
        "checked_at_ms": int(time.time() * 1000),
        "expected_sha": str(expected_sha),
        "failed_checks": [reason],
        "runtime_flags_changed": False,
        "campaign_started": False,
        "mainnet_enabled": False,
    }
    if error_type:
        payload["error_type"] = error_type
    return payload


def _emit(payload: Mapping[str, Any], output: str) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    print(serialized, end="")
    if not output:
        return
    path = Path(output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _full_sha(value: Any) -> bool:
    text = str(value).strip().lower()
    return len(text) == 40 and all(char in "0123456789abcdef" for char in text)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


if __name__ == "__main__":
    raise SystemExit(main())
