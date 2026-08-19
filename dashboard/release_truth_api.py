"""Authoritative read-only Truth/Release Center and fail-closed release gate.

This module aggregates existing runtime contracts. It deliberately reports
UNKNOWN/STALE when evidence is absent instead of manufacturing a healthy state.
It has no deployment or execution authority.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping, Sequence

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from telegram_runtime_state import canonical_state_from_app

from .release_status_api import release_status

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_TRUE = {"1", "true", "yes", "on"}


def _sha(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA_PATTERN.fullmatch(text) else "UNKNOWN"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE


def _component(health: Mapping[str, Any], name: str) -> dict[str, Any]:
    for item in health.get("components", ()):
        if isinstance(item, Mapping) and str(item.get("component")) == name:
            return dict(item)
    return {
        "component": name,
        "status": "UNKNOWN",
        "evidence": [],
        "blockers": [f"{name} health evidence is unavailable"],
        "recovery": [],
    }


def _ci_evidence(app: FastAPI) -> dict[str, Any]:
    supplied = getattr(app.state, "release_gate_ci_evidence", None)
    if isinstance(supplied, Mapping):
        return {
            "main_sha": _sha(supplied.get("main_sha")),
            "status": str(supplied.get("status") or "UNKNOWN").upper(),
            "fresh": supplied.get("fresh") is True,
            "checked_at_ms": supplied.get("checked_at_ms"),
            "source": str(supplied.get("source") or "release_process"),
        }
    return {
        "main_sha": _sha(os.getenv("SHARIPOVAI_MAIN_SHA")),
        "status": os.getenv("SHARIPOVAI_MAIN_CI_STATUS", "UNKNOWN").strip().upper() or "UNKNOWN",
        "fresh": _truthy(os.getenv("SHARIPOVAI_MAIN_CI_FRESH")),
        "checked_at_ms": None,
        "source": "release_environment",
    }


def _migration_evidence(app: FastAPI) -> dict[str, Any]:
    supplied = getattr(app.state, "release_gate_migration_evidence", None)
    if isinstance(supplied, Mapping):
        blockers = supplied.get("blockers")
        if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes)):
            normalized = [str(item) for item in blockers if str(item).strip()]
        else:
            normalized = []
        known = supplied.get("known") is True
        return {"known": known, "blockers": normalized, "source": str(supplied.get("source") or "release_process")}
    return {"known": False, "blockers": [], "source": "unavailable"}


def _reason_category(reason: Any) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "UNKNOWN"
    if any(token in text for token in ("stale", "market", "quote", "evidence", "data", "source")):
        return "DATA"
    if any(token in text for token in ("risk", "security", "veto", "kill", "safety", "blocked")):
        return "SAFETY"
    if any(token in text for token in ("budget", "exposure", "fee", "slippage", "cost", "size", "notional")):
        return "ECONOMIC"
    return "OTHER"


def evaluate_release_gate(
    *,
    release: Mapping[str, Any],
    health: Mapping[str, Any],
    ci: Mapping[str, Any],
    migration: Mapping[str, Any],
) -> dict[str, Any]:
    """Return PASS/WAIT/BLOCK without granting deployment authority."""

    blockers: list[str] = []
    waiting: list[str] = []

    if release.get("execution_kill_switch") is not True:
        blockers.append("execution kill switch is not confirmed active")
    if release.get("mainnet_execution_compiled") is not False:
        blockers.append("mainnet execution is not confirmed unavailable")
    if release.get("live_execution_enabled") is not False:
        blockers.append("live execution is enabled or not safely reported")
    if release.get("testnet_execution_enabled") is not False:
        blockers.append("testnet execution is enabled or not safely reported")
    if release.get("autonomous_testnet_enabled") is not False:
        blockers.append("autonomous testnet execution is enabled or not safely reported")
    if release.get("autonomous_testnet_bridge_enabled") is not False:
        blockers.append("autonomous testnet bridge is enabled or not safely reported")

    storage = _component(health, "storage")
    backup = _component(health, "backup")
    if str(storage.get("status", "UNKNOWN")).lower() != "healthy":
        waiting.append(f"storage headroom is not healthy: {storage.get('status', 'UNKNOWN')}")
    if str(backup.get("status", "UNKNOWN")).lower() != "healthy":
        waiting.append(f"backup freshness is not healthy: {backup.get('status', 'UNKNOWN')}")

    if _sha(ci.get("main_sha")) == "UNKNOWN":
        waiting.append("exact main SHA evidence is unavailable")
    if str(ci.get("status") or "UNKNOWN").upper() != "SUCCESS":
        waiting.append(f"exact-main CI is not SUCCESS: {ci.get('status', 'UNKNOWN')}")
    if ci.get("fresh") is not True:
        waiting.append("exact-main CI freshness is not confirmed")

    if migration.get("known") is not True:
        waiting.append("required migration blocker state is unknown")
    elif migration.get("blockers"):
        waiting.extend(f"required migration blocker: {item}" for item in migration.get("blockers", ()))

    verdict = "BLOCK" if blockers else "WAIT" if waiting else "PASS"
    reasons = blockers + waiting
    return {
        "verdict": verdict,
        "reasons": reasons,
        "blocking_reasons": blockers,
        "waiting_reasons": waiting,
        "deployment_authority": False,
        "owner_action": "confirm_production_deploy" if verdict == "PASS" else None,
    }


def build_release_truth(app: FastAPI, *, now: float | None = None) -> dict[str, Any]:
    """Aggregate existing sources into one truthful, read-only snapshot."""

    checked_at_ms = int((time.time() if now is None else float(now)) * 1000)
    release = release_status()

    health_center = getattr(app.state, "system_health_center", None)
    try:
        health = health_center.snapshot() if health_center is not None else {"status": "UNKNOWN", "components": []}
    except Exception as exc:
        health = {"status": "UNKNOWN", "components": [], "error": f"{type(exc).__name__}: {exc}"}

    monitor = getattr(app.state, "ai_organ_runtime_monitor", None)
    try:
        organs = monitor.snapshot() if monitor is not None else {"status": "UNKNOWN", "organs": []}
    except Exception as exc:
        organs = {"status": "UNKNOWN", "organs": [], "error": f"{type(exc).__name__}: {exc}"}

    paper = canonical_state_from_app(app)
    loop = getattr(app.state, "autonomous_paper_loop", None)
    paper_owner = type(loop).__name__ if loop is not None else "UNKNOWN"

    ci = _ci_evidence(app)
    migration = _migration_evidence(app)
    gate = evaluate_release_gate(release=release, health=health, ci=ci, migration=migration)

    latest_action = paper.get("last_action") or "UNKNOWN"
    latest_reason = paper.get("last_reason") or "UNKNOWN"

    return {
        "status": "ok",
        "checked_at_ms": checked_at_ms,
        "architecture_version": os.getenv("SHARIPOVAI_ARCHITECTURE_VERSION", "UNKNOWN").strip() or "UNKNOWN",
        "identity": {
            "production_release_sha": _sha(release.get("release_sha")),
            "github_main_sha": ci.get("main_sha", "UNKNOWN"),
            "exact_main_ci": ci,
        },
        "paper_runtime": {
            "decision_owner": paper_owner,
            "source_of_truth": paper.get("source_of_truth", "UNKNOWN"),
            "state_status": paper.get("status", "UNKNOWN"),
            "latest_action": latest_action,
            "latest_reason": latest_reason,
            "reason_category": _reason_category(latest_reason),
            "trade_count": paper.get("trade_count"),
            "open_positions": paper.get("open_positions"),
        },
        "ai_organs": organs,
        "risk_security_veto": {
            "status": "UNKNOWN",
            "reason": "no canonical latest-veto projection is exposed by current runtime contracts",
        },
        "v2_cohort_metrics": {
            "status": "UNKNOWN",
            "reason": "current canonical paper projection does not expose an isolated V2 cohort",
        },
        "storage": _component(health, "storage"),
        "backup": _component(health, "backup"),
        "system_health": {
            "status": health.get("status", "UNKNOWN"),
            "checked_at_ms": health.get("checked_at_ms"),
        },
        "safety": {
            "execution_kill_switch": release.get("execution_kill_switch"),
            "mainnet_execution_compiled": release.get("mainnet_execution_compiled"),
            "live_execution_enabled": release.get("live_execution_enabled"),
            "testnet_execution_enabled": release.get("testnet_execution_enabled"),
            "autonomous_testnet_enabled": release.get("autonomous_testnet_enabled"),
            "autonomous_testnet_bridge_enabled": release.get("autonomous_testnet_bridge_enabled"),
        },
        "migration": migration,
        "release_gate": gate,
        "sources": {
            "release": "dashboard.release_status_api.release_status",
            "health": "app.state.system_health_center.snapshot",
            "ai_organs": "app.state.ai_organ_runtime_monitor.snapshot",
            "paper": "telegram_runtime_state.canonical_state_from_app",
            "ci": ci.get("source", "UNKNOWN"),
            "migration": migration.get("source", "UNKNOWN"),
        },
    }


def install_release_truth_api(app: FastAPI) -> None:
    if getattr(app.state, "release_truth_api_installed", False):
        return
    app.state.release_truth_api_installed = True

    @app.get("/api/system/release-truth")
    async def get_release_truth() -> JSONResponse:
        return JSONResponse(build_release_truth(app), headers={"Cache-Control": "no-store"})


__all__ = ["build_release_truth", "evaluate_release_gate", "install_release_truth_api"]
