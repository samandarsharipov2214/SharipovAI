"""Loopback-only, read-only runtime evidence for SharipovAI audits.

The endpoint exposes no credentials, accepts no body and performs no recovery or
financial action. It is public only at the session middleware layer; this module
then rejects every non-loopback client.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_LOOPBACK = {"127.0.0.1", "::1"}
_TRUE = {"1", "true", "yes", "on"}


def _safe_call(target: Any, method: str, default: Any) -> Any:
    function: Callable[..., Any] | None = getattr(target, method, None) if target is not None else None
    if not callable(function):
        return default
    try:
        return function()
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in _LOOPBACK:
        return True
    # Starlette TestClient uses this synthetic host. Never permit it in production.
    return host == "testclient" and os.getenv("ENVIRONMENT", "").strip().lower() not in {"production", "prod"}


def install_local_audit_api(app: FastAPI) -> None:
    if getattr(app.state, "local_audit_api_installed", False):
        return
    app.state.local_audit_api_installed = True

    @app.get("/api/system/local-audit")
    def local_audit(request: Request):
        if not _is_loopback(request):
            return JSONResponse({"status": "forbidden", "detail": "loopback only"}, status_code=403)

        health_center = getattr(app.state, "system_health_center", None)
        health = _safe_call(health_center, "snapshot", {"status": "unavailable", "components": []})
        database = _safe_call(getattr(app.state, "project_database", None), "health", {"status": "unavailable"})
        market = _safe_call(getattr(app.state, "bybit_websocket_worker", None), "status", {"status": "unavailable"})
        account = _safe_call(getattr(app.state, "bybit_account_service", None), "status", {"status": "unavailable"})
        news = _safe_call(getattr(app.state, "news_agent_network", None), "status", {"status": "unavailable"})
        organs = _safe_call(getattr(app.state, "ai_organ_runtime_monitor", None), "snapshot", {"status": "unavailable"})

        return {
            "status": "ok",
            "checked_at_ms": int(time.time() * 1000),
            "read_only": True,
            "loopback_verified": True,
            "route_count": len(app.routes),
            "system": health,
            "database": database,
            "market": market,
            "bybit_account": account,
            "news": news,
            "ai_organs": organs,
            "execution": {
                "kill_switch": os.getenv("EXECUTION_KILL_SWITCH", "0").strip().lower() in _TRUE,
                "live_enabled": os.getenv("EXCHANGE_LIVE_TRADING_ENABLED", "0").strip().lower() in _TRUE,
                "testnet_enabled": os.getenv("TESTNET_EXECUTION_ENABLED", "0").strip().lower() in _TRUE,
                "mode": os.getenv("EXCHANGE_MODE", "unknown"),
            },
        }


__all__ = ["install_local_audit_api"]
