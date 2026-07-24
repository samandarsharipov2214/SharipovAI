"""Public, non-secret release provenance for exact-SHA deployment verification."""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE


def _release_sha() -> str:
    value = os.getenv("SHARIPOVAI_BUILD_SHA", "").strip().lower()
    return value if _SHA_PATTERN.fullmatch(value) else "unknown"


def release_status() -> dict[str, Any]:
    """Return only public deployment provenance and fail-closed safety state."""

    return {
        "status": "ok",
        "release_sha": _release_sha(),
        "build_date": os.getenv("SHARIPOVAI_BUILD_DATE", "unknown").strip() or "unknown",
        "environment": os.getenv("ENVIRONMENT", "unknown").strip().lower() or "unknown",
        "auth_enabled": not _flag("SHARIPOVAI_DISABLE_AUTH"),
        "database_required": _flag("SHARIPOVAI_DATABASE_REQUIRED", "1"),
        "exchange_mode": os.getenv("EXCHANGE_MODE", "sandbox").strip().lower(),
        "mainnet_execution_compiled": bool(MAINNET_EXECUTION_COMPILED),
        "execution_kill_switch": _flag("EXECUTION_KILL_SWITCH", "1"),
        "testnet_execution_enabled": _flag("TESTNET_EXECUTION_ENABLED"),
        "autonomous_testnet_enabled": _flag("AUTONOMOUS_TESTNET_ENABLED"),
        "autonomous_testnet_bridge_enabled": _flag("AUTONOMOUS_TESTNET_BRIDGE_ENABLED"),
        "private_order_stream_enabled": _flag("FEATURE_BYBIT_PRIVATE_ORDER_WS"),
        "runtime_fill_harvester_enabled": _flag("RUNTIME_FILL_HARVESTER_ENABLED"),
        "scheduled_campaign_orchestrator_enabled": _flag("SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED"),
        "live_execution_enabled": (
            _flag("EXCHANGE_LIVE_TRADING_ENABLED")
            or _flag("FEATURE_BYBIT_LIVE_EXECUTION")
        ),
    }


def install_release_status_api(app: FastAPI) -> None:
    if getattr(app.state, "release_status_api_installed", False):
        return
    app.state.release_status_api_installed = True

    @app.get("/api/release/status")
    async def get_release_status() -> JSONResponse:
        return JSONResponse(
            release_status(),
            headers={"Cache-Control": "no-store"},
        )


__all__ = ["install_release_status_api", "release_status"]
