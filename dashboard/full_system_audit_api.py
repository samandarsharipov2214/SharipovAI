"""Read-only audit of the ten critical SharipovAI operating areas."""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI


REQUIRED_ROUTES: dict[str, tuple[str, ...]] = {
    "api": ("/api/health", "/api/system/health"),
    "ai": ("/api/ai-bots", "/api/run"),
    "integration": ("/api/system/ai-organs", "/api/evidence-vault/recent"),
    "realtime": ("/api/market/bybit-websocket/status", "/api/social-news"),
    "paper_execution": ("/api/virtual-account/state",),
    "decisions": ("/api/run", "/api/ai-control-center/daily-report"),
    "errors": ("/api/system/health", "/api/system/recovery-plan"),
    "vps": ("/api/system/health",),
}


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _check(name: str, ok: bool, evidence: list[str], blockers: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if ok else "failed",
        "evidence": evidence,
        "blockers": blockers or [],
    }


def build_audit(app: FastAPI) -> dict[str, Any]:
    paths = _route_paths(app)
    checks: list[dict[str, Any]] = []

    for key, required in REQUIRED_ROUTES.items():
        missing = [path for path in required if path not in paths]
        checks.append(_check(key, not missing, [f"route={path}" for path in required if path in paths], [f"missing_route={path}" for path in missing]))

    state_names = set(vars(app.state).keys())
    runtime_objects = {
        "database": "project_database",
        "market_worker": "bybit_websocket_worker",
        "news_network": "news_agent_network",
        "ai_monitor": "ai_organ_runtime_monitor",
        "health_center": "system_health_center",
    }
    missing_runtime = [label for label, attr in runtime_objects.items() if attr not in state_names]
    checks.append(_check("runtime_objects", not missing_runtime, [f"state={attr}" for attr in runtime_objects.values() if attr in state_names], [f"missing_state={name}" for name in missing_runtime]))

    live_locked = not any(os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"} for name in ("EXCHANGE_LIVE_TRADING_ENABLED", "TESTNET_EXECUTION_ENABLED"))
    checks.append(_check("safe_trading", live_locked, ["financial_execution_locked"] if live_locked else [], [] if live_locked else ["financial_execution_enabled"]))

    duplicate_paths: dict[str, int] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path:
            duplicate_paths[path] = duplicate_paths.get(path, 0) + 1
    duplicates = sorted(path for path, count in duplicate_paths.items() if count > 1 and path.startswith("/api/"))
    checks.append(_check("dead_code_and_duplicates", not duplicates, [f"api_routes={sum(1 for p in paths if p.startswith('/api/'))}"], [f"duplicate_route={path}" for path in duplicates]))

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


__all__ = ["REQUIRED_ROUTES", "build_audit", "install_full_system_audit_api"]
