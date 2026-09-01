"""Canonical runtime truth and read-only compatibility adapters.

The old PaperActivityEngine URLs remain readable for compatibility, but they no
longer own state, start a worker, or accept mutations. CouncilAuthorizedPaperLoop
is the only virtual-account runtime owner.
"""
from __future__ import annotations

import os
from html import escape
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

_DEPRECATED_READ_PATHS = {
    "/api/paper-activity/state",
    "/api/virtual-account/state",
    "/api/paper-activity/trades",
    "/api/virtual-account/trades",
    "/api/demo/state/shared",
}
_DEPRECATED_WRITE_PATHS = {
    "/api/paper-activity/tick",
    "/api/virtual-account/tick",
    "/api/paper-activity/catch-up",
    "/api/virtual-account/catch-up",
    "/api/paper-activity/reset",
}
_DEPRECATED_PAGE_PATHS = {"/paper-activity", "/virtual-account"}
_DEPRECATION_HEADERS = {
    "Deprecation": "true",
    "Link": '</api/autonomous-paper/status>; rel="successor-version"',
    "Cache-Control": "no-store",
}


def _loop(app: FastAPI) -> Any:
    loop = getattr(app.state, "autonomous_paper_loop", None)
    if loop is None or not callable(getattr(loop, "snapshot", None)):
        raise HTTPException(
            status_code=503,
            detail={
                "status": "canonical_paper_runtime_unavailable",
                "source_of_truth": "CouncilAuthorizedPaperLoop",
            },
        )
    return loop


def _snapshot(app: FastAPI) -> dict[str, Any]:
    loop = _loop(app)
    lock = getattr(loop, "_lock", None)
    if lock is not None:
        from autonomous_trading.status_snapshot import nonblocking_loop_snapshot

        value = nonblocking_loop_snapshot(loop)
    else:
        value = loop.snapshot()
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="canonical paper snapshot is invalid")
    return dict(value)


def _bounded_limit(value: int | None, *, default: int = 200) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), 5_000)


def _history(loop: Any, name: str, *, limit: int) -> list[dict[str, Any]]:
    reader = getattr(loop, name, None)
    if not callable(reader):
        return []
    value = reader(limit=limit)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _trades(app: FastAPI, *, limit: int = 200) -> list[dict[str, Any]]:
    loop = _loop(app)
    rows = _history(loop, "trade_history", limit=_bounded_limit(limit))
    if rows:
        return rows
    raw = _snapshot(app).get("trades")
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _events(app: FastAPI, *, limit: int = 200) -> list[dict[str, Any]]:
    return _history(_loop(app), "event_history", limit=_bounded_limit(limit))


def _summary(snapshot: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    positions = snapshot.get("positions")
    if isinstance(positions, dict):
        open_positions = len(positions)
    elif isinstance(positions, list):
        open_positions = len(positions)
    else:
        open_positions = 0
    closed_positions = sum(
        1 for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"
    )
    realized = float(snapshot.get("realized_pnl", 0.0) or 0.0)
    unrealized = float(snapshot.get("unrealized_pnl", 0.0) or 0.0)
    market = snapshot.get("market_stream")
    if not isinstance(market, dict):
        market = {}
    return {
        "equity": snapshot.get("equity"),
        "cash": snapshot.get("cash"),
        "open_positions": open_positions,
        "closed_positions": closed_positions,
        "trade_count": int(snapshot.get("trade_history_count") or len(trades)),
        "net_pnl": realized + unrealized,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_fees": snapshot.get("total_fees", 0.0),
        "real_orders_blocked": snapshot.get("real_execution_enabled") is not True,
        "market_price_accounting": market.get("verified") is True,
        "worker_running": snapshot.get("worker_running") is True,
        "database_backed": snapshot.get("database_backed") is True,
        "source_of_truth": "CouncilAuthorizedPaperLoop",
    }


def _canonical_payload(app: FastAPI, *, limit: int = 200) -> dict[str, Any]:
    snapshot = _snapshot(app)
    trades = _trades(app, limit=limit)
    summary = _summary(snapshot, trades)
    return {
        "status": str(snapshot.get("status") or "ok"),
        "source_of_truth": "CouncilAuthorizedPaperLoop",
        "canonical_endpoint": "/api/autonomous-paper/status",
        "summary": summary,
        "state": {
            **snapshot,
            "summary": summary,
            "trades": trades,
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "legacy_virtual_account_deprecated": True,
            "mutation_on_read": False,
        },
        "trades": trades,
    }


def _organ_snapshot(app: FastAPI) -> dict[str, Any]:
    monitor = getattr(app.state, "ai_organ_runtime_monitor", None)
    if monitor is None or not callable(getattr(monitor, "snapshot", None)):
        return {
            "status": "unavailable",
            "organ_count": 0,
            "counts": {"healthy": 0, "degraded": 0, "blocked": 0},
            "organs": [],
            "database_backed": False,
        }
    try:
        value = monitor.snapshot()
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "organ_count": 0,
            "counts": {"healthy": 0, "degraded": 0, "blocked": 0},
            "organs": [],
            "database_backed": False,
        }
    return dict(value) if isinstance(value, dict) else {"status": "unavailable"}


def _truthy(name: str, *, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _safety_state() -> dict[str, Any]:
    kill_switch = _truthy("EXECUTION_KILL_SWITCH", default=True)
    testnet = _truthy("TESTNET_EXECUTION_ENABLED") or _truthy("AUTONOMOUS_TESTNET_ENABLED")
    live = _truthy("EXCHANGE_LIVE_TRADING_ENABLED") or _truthy("FEATURE_BYBIT_LIVE_EXECUTION")
    safe = kill_switch and not testnet and not live
    return {
        "status": "locked" if safe else "unsafe",
        "execution_kill_switch": kill_switch,
        "testnet_execution_enabled": testnet,
        "live_execution_enabled": live,
        "real_orders_blocked": safe,
    }


def _runtime_truth(app: FastAPI) -> dict[str, Any]:
    paper = _canonical_payload(app, limit=200)
    organs = _organ_snapshot(app)
    safety = _safety_state()
    organ_status = str(organs.get("status") or "unavailable").lower()
    paper_summary = paper["summary"]
    if safety["status"] != "locked" or organ_status == "blocked":
        status = "blocked"
    elif organ_status in {"degraded", "unavailable"} or not paper_summary.get("database_backed"):
        status = "degraded"
    else:
        status = "healthy"
    return {
        "status": status,
        "truth_contract": "canonical_runtime_v1",
        "source_of_truth": {
            "paper": "CouncilAuthorizedPaperLoop",
            "risk": "risk_engine.canonical_service",
            "organs": "AIOrganRuntimeMonitor",
            "database": "ProjectDatabase",
        },
        "paper": paper,
        "organs": organs,
        "safety": safety,
        "legacy": {
            "api_run_allowed_for_ui": False,
            "paper_activity_engine_active": False,
            "virtual_account_routes_deprecated": True,
        },
    }


def _deprecated_write(path: str) -> JSONResponse:
    replacement = "/api/autonomous-paper/tick" if path.endswith("/tick") else "/api/autonomous-paper/status"
    return JSONResponse(
        status_code=410,
        headers=_DEPRECATION_HEADERS,
        content={
            "status": "deprecated_operation_blocked",
            "path": path,
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "replacement": replacement,
            "automatic_legacy_mutation": False,
        },
    )


def _remove_legacy_routes(app: FastAPI) -> None:
    targets = _DEPRECATED_READ_PATHS | _DEPRECATED_WRITE_PATHS | _DEPRECATED_PAGE_PATHS
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if str(getattr(route, "path", "")) not in targets
    ]


def _remove_legacy_startup(app: FastAPI) -> None:
    handlers = list(getattr(app.router, "on_startup", []))
    app.router.on_startup[:] = [
        handler
        for handler in handlers
        if not (
            getattr(handler, "__name__", "") == "paper_activity_startup"
            or getattr(handler, "__module__", "") == "paper_activity_autorun"
        )
    ]


def install_canonical_runtime_compat_api(app: FastAPI) -> None:
    """Install canonical truth and retire legacy virtual-account ownership."""

    if getattr(app.state, "canonical_runtime_compat_api_installed", False):
        return
    app.state.canonical_runtime_compat_api_installed = True
    _remove_legacy_routes(app)
    _remove_legacy_startup(app)

    @app.middleware("http")
    async def canonical_demo_state(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/api/demo/state":
            payload = _canonical_payload(app)
            return JSONResponse(
                {**payload, "deprecated": True, "replacement": "/api/autonomous-paper/status"},
                headers=_DEPRECATION_HEADERS,
            )
        return await call_next(request)

    @app.get("/api/system/runtime-truth")
    def runtime_truth() -> dict[str, Any]:
        return _runtime_truth(app)

    @app.get("/api/autonomous-paper/trades")
    def autonomous_paper_trades(limit: int = 200) -> dict[str, Any]:
        rows = _trades(app, limit=_bounded_limit(limit))
        return {
            "status": "ok",
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "count": len(rows),
            "trades": rows,
        }

    @app.get("/api/autonomous-paper/events")
    def autonomous_paper_events(limit: int = 200) -> dict[str, Any]:
        rows = _events(app, limit=_bounded_limit(limit))
        return {
            "status": "ok",
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "count": len(rows),
            "events": rows,
        }

    @app.get("/api/paper-activity/state")
    @app.get("/api/virtual-account/state")
    @app.get("/api/demo/state/shared")
    def deprecated_virtual_state() -> JSONResponse:
        payload = _canonical_payload(app)
        return JSONResponse(
            {**payload, "deprecated": True, "replacement": "/api/autonomous-paper/status"},
            headers=_DEPRECATION_HEADERS,
        )

    @app.get("/api/paper-activity/trades")
    @app.get("/api/virtual-account/trades")
    def deprecated_virtual_trades() -> JSONResponse:
        payload = _canonical_payload(app, limit=1_000)
        return JSONResponse(
            {
                "status": payload["status"],
                "deprecated": True,
                "replacement": "/api/autonomous-paper/trades",
                "source_of_truth": payload["source_of_truth"],
                "summary": payload["summary"],
                "trades": payload["trades"],
            },
            headers=_DEPRECATION_HEADERS,
        )

    @app.post("/api/paper-activity/tick")
    @app.post("/api/virtual-account/tick")
    @app.post("/api/paper-activity/catch-up")
    @app.post("/api/virtual-account/catch-up")
    @app.post("/api/paper-activity/reset")
    def deprecated_virtual_write(request: Request) -> JSONResponse:
        return _deprecated_write(request.url.path)

    @app.get("/paper-activity", response_class=HTMLResponse)
    @app.get("/virtual-account", response_class=HTMLResponse)
    def deprecated_virtual_page() -> HTMLResponse:
        return _canonical_page(app)


def _canonical_page(app: FastAPI) -> HTMLResponse:
    payload = _canonical_payload(app)
    body = "".join(
        f"<li><b>{escape(str(key))}</b>: {escape(str(value))}</li>"
        for key, value in payload["summary"].items()
    )
    return HTMLResponse(
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>SharipovAI · Canonical Virtual Account</title></head><body>"
        "<main><h1>Canonical Virtual Account</h1>"
        "<p>Старый PaperActivityEngine отключён. Единственный источник состояния — "
        "<code>CouncilAuthorizedPaperLoop</code>.</p>"
        f"<ul>{body}</ul><p><a href='/api/autonomous-paper/status'>Canonical JSON</a></p>"
        "</main></body></html>",
        headers=_DEPRECATION_HEADERS,
    )


__all__ = ["install_canonical_runtime_compat_api"]
