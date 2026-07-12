"""Read-only audit of the ten critical SharipovAI operating areas.

The audit observes existing owners only. It never creates an AI organ, starts a
worker, performs recovery, changes feature flags, or submits an order.
"""
from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI


REQUIRED_ROUTES: dict[str, tuple[str, ...]] = {
    "api": ("/api/health", "/api/system/health"),
    "ai": ("/api/ai-bots", "/api/run"),
    "integration": ("/api/system/ai-organs", "/api/evidence-vault/snapshot"),
    "realtime": ("/api/market/bybit-websocket/status", "/api/social-news"),
    "paper_execution": ("/api/virtual-account/state",),
    "decisions": ("/api/run", "/api/ai-control-center/daily-report"),
    "errors": ("/api/system/health", "/api/system/recovery-plan"),
    "vps": ("/api/system/health",),
}

_TRUE = {"1", "true", "yes", "on"}
_SENTINEL = object()


def _route_paths(app: FastAPI) -> set[str]:
    return {str(getattr(route, "path", "")) for route in app.routes if getattr(route, "path", "")}


def _route_method_counts(app: FastAPI) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        if not path.startswith("/api/"):
            continue
        methods = getattr(route, "methods", None) or {"ANY"}
        for method in methods:
            clean = str(method).upper()
            if clean in {"HEAD", "OPTIONS"}:
                continue
            counts[(clean, path)] += 1
    return counts


def _check(name: str, ok: bool, evidence: list[str], blockers: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if ok else "failed",
        "evidence": evidence,
        "blockers": blockers or [],
    }


def _state_value(app: FastAPI, name: str) -> Any:
    return getattr(app.state, name, _SENTINEL)


def _mapping_call(owner: Any, method_name: str) -> tuple[dict[str, Any] | None, str | None]:
    method = getattr(owner, method_name, None)
    if not callable(method):
        return None, f"{method_name} is unavailable"
    try:
        value = method()
    except Exception as exc:  # observation must not crash the audit endpoint
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(value, Mapping):
        return None, f"{method_name} returned a non-object"
    return dict(value), None


def _runtime_checks(app: FastAPI) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    database = _state_value(app, "project_database")
    db_status, db_error = _mapping_call(database, "health") if database is not _SENTINEL else (None, "missing")
    db_ok = bool(db_status and db_status.get("status") == "ok")
    checks.append(
        _check(
            "database_runtime",
            db_ok,
            [f"backend={db_status.get('backend', 'unknown')}"] if db_status else [],
            [] if db_ok else [f"database={db_error or db_status}"],
        )
    )

    worker = _state_value(app, "bybit_websocket_worker")
    market, market_error = _mapping_call(worker, "status") if worker is not _SENTINEL else (None, "missing")
    market_ok = bool(
        market
        and market.get("enabled") is True
        and market.get("worker_running") is True
        and market.get("verified") is True
        and market.get("database_backed") is True
        and market.get("synthetic_fallback_used") is False
    )
    market_evidence = [] if market is None else [
        f"enabled={market.get('enabled')}",
        f"running={market.get('worker_running')}",
        f"verified={market.get('verified')}",
        f"database_backed={market.get('database_backed')}",
    ]
    checks.append(
        _check(
            "market_realtime_runtime",
            market_ok,
            market_evidence,
            [] if market_ok else [f"market_runtime={market_error or market}"],
        )
    )

    news = _state_value(app, "news_agent_network")
    news_status, news_error = _mapping_call(news, "snapshot") if news is not _SENTINEL else (None, "missing")
    news_ok = bool(
        news_status
        and news_status.get("database_backed") is True
        and str(news_status.get("status", "")).lower() in {"running", "ok", "active"}
        and not str(news_status.get("last_error") or "").strip()
    )
    news_evidence = [] if news_status is None else [
        f"status={news_status.get('status')}",
        f"database_backed={news_status.get('database_backed')}",
    ]
    checks.append(
        _check(
            "news_realtime_runtime",
            news_ok,
            news_evidence,
            [] if news_ok else [f"news_runtime={news_error or news_status}"],
        )
    )

    monitor = _state_value(app, "ai_organ_runtime_monitor")
    organs, organs_error = _mapping_call(monitor, "snapshot") if monitor is not _SENTINEL else (None, "missing")
    organs_ok = bool(
        organs
        and organs.get("status") == "healthy"
        and int(organs.get("organ_count", 0)) == 9
        and organs.get("monitor_running") is True
    )
    checks.append(
        _check(
            "ai_organs_runtime",
            organs_ok,
            [] if organs is None else [
                f"status={organs.get('status')}",
                f"organ_count={organs.get('organ_count')}",
                f"monitor_running={organs.get('monitor_running')}",
            ],
            [] if organs_ok else [f"ai_organs={organs_error or organs}"],
        )
    )

    center = _state_value(app, "system_health_center")
    health, health_error = _mapping_call(center, "snapshot") if center is not _SENTINEL else (None, "missing")
    health_ok = bool(health and health.get("status") == "healthy" and health.get("safe_mode") is False)
    checks.append(
        _check(
            "vps_runtime_health",
            health_ok,
            [] if health is None else [f"status={health.get('status')}", f"safe_mode={health.get('safe_mode')}"],
            [] if health_ok else [f"system_health={health_error or health}"],
        )
    )
    return checks


def _financial_safety_check() -> dict[str, Any]:
    unsafe_enabled = [
        name
        for name in (
            "EXCHANGE_LIVE_TRADING_ENABLED",
            "TESTNET_EXECUTION_ENABLED",
            "AUTONOMOUS_TESTNET_ENABLED",
            "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        )
        if _truthy(name)
    ]
    kill_switch = _truthy("EXECUTION_KILL_SWITCH")
    ok = kill_switch and not unsafe_enabled
    evidence = ["execution_kill_switch_active"] if kill_switch else []
    if not unsafe_enabled:
        evidence.append("all_testnet_and_mainnet_execution_gates_locked")
    blockers = ([] if kill_switch else ["execution_kill_switch_disabled"]) + [
        f"unsafe_flag_enabled={name}" for name in unsafe_enabled
    ]
    return _check("safe_trading", ok, evidence, blockers)


def build_audit(app: FastAPI) -> dict[str, Any]:
    paths = _route_paths(app)
    checks: list[dict[str, Any]] = []

    for key, required in REQUIRED_ROUTES.items():
        missing = [path for path in required if path not in paths]
        checks.append(
            _check(
                key,
                not missing,
                [f"route={path}" for path in required if path in paths],
                [f"missing_route={path}" for path in missing],
            )
        )

    runtime_objects = {
        "database": "project_database",
        "market_worker": "bybit_websocket_worker",
        "news_network": "news_agent_network",
        "ai_monitor": "ai_organ_runtime_monitor",
        "health_center": "system_health_center",
    }
    missing_runtime = [label for label, attr in runtime_objects.items() if _state_value(app, attr) is _SENTINEL]
    checks.append(
        _check(
            "runtime_objects",
            not missing_runtime,
            [f"state={attr}" for attr in runtime_objects.values() if _state_value(app, attr) is not _SENTINEL],
            [f"missing_state={name}" for name in missing_runtime],
        )
    )
    checks.extend(_runtime_checks(app))
    checks.append(_financial_safety_check())

    method_counts = _route_method_counts(app)
    duplicates = sorted((method, path) for (method, path), count in method_counts.items() if count > 1)
    checks.append(
        _check(
            "dead_code_and_duplicates",
            not duplicates,
            [f"api_method_routes={len(method_counts)}"],
            [f"duplicate_route={method} {path}" for method, path in duplicates],
        )
    )

    passed = sum(item["status"] == "passed" for item in checks)
    return {
        "status": "passed" if passed == len(checks) else "attention_required",
        "checked_at_ms": int(time.time() * 1000),
        "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks)},
        "checks": checks,
        "read_only": True,
        "orders_sent": False,
        "automatic_recovery": False,
    }


def install_full_system_audit_api(app: FastAPI) -> None:
    if getattr(app.state, "full_system_audit_api_installed", False):
        return
    app.state.full_system_audit_api_installed = True

    @app.get("/api/system/full-audit")
    def full_audit() -> dict[str, Any]:
        result = build_audit(app)
        database = getattr(app.state, "project_database", None)
        put_json = getattr(database, "put_json", None)
        if callable(put_json):
            try:
                put_json("system_runtime", "full_audit", result)
            except Exception:
                pass
        return result


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE


__all__ = ["REQUIRED_ROUTES", "build_audit", "install_full_system_audit_api"]
