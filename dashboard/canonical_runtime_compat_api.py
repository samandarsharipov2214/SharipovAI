"""Compatibility routes backed only by the canonical CouncilAuthorizedPaperLoop.

Legacy URLs remain available for read compatibility, but they no longer create,
start or mutate ``PaperActivityEngine``. The canonical autonomous paper loop is
the sole virtual-account source of truth.
"""
from __future__ import annotations

from html import escape
from typing import Any, Callable

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
    value = _loop(app).snapshot()
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="canonical paper snapshot is invalid")
    return dict(value)


def _trades(loop: Any, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    history = getattr(loop, "trade_history", None)
    if callable(history):
        value = history(limit=1000)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    raw = snapshot.get("trades")
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _legacy_summary(snapshot: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    positions = snapshot.get("positions")
    open_positions = len(positions) if isinstance(positions, dict) else len(positions or []) if isinstance(positions, list) else 0
    closed_positions = sum(1 for trade in trades if str(trade.get("status", "")).upper() == "CLOSED")
    realized = float(snapshot.get("realized_pnl", 0.0) or 0.0)
    unrealized = float(snapshot.get("unrealized_pnl", 0.0) or 0.0)
    market = snapshot.get("market_stream") if isinstance(snapshot.get("market_stream"), dict) else {}
    return {
        "equity": snapshot.get("equity"),
        "cash": snapshot.get("cash"),
        "open_positions": open_positions,
        "closed_positions": closed_positions,
        "trade_count": len(trades),
        "net_pnl": realized + unrealized,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_fees": snapshot.get("total_fees", 0.0),
        "real_orders_blocked": snapshot.get("real_execution_enabled") is not True,
        "market_price_accounting": market.get("verified") is True,
        "worker_running": snapshot.get("worker_running") is True,
        "source_of_truth": "CouncilAuthorizedPaperLoop",
    }


def _compat_payload(app: FastAPI) -> dict[str, Any]:
    loop = _loop(app)
    snapshot = _snapshot(app)
    trades = _trades(loop, snapshot)
    state = {
        **snapshot,
        "summary": _legacy_summary(snapshot, trades),
        "trades": trades,
        "deprecated": True,
        "legacy_virtual_account_deprecated": True,
        "source_of_truth": "CouncilAuthorizedPaperLoop",
        "canonical_endpoint": "/api/autonomous-paper/status",
        "mutation_on_read": False,
    }
    return {
        "status": str(snapshot.get("status") or "ok"),
        "deprecated": True,
        "replacement": "/api/autonomous-paper/status",
        "source_of_truth": "CouncilAuthorizedPaperLoop",
        "state": state,
        "summary": state["summary"],
        "trades": trades,
    }


def _deprecated_write(path: str) -> JSONResponse:
    return JSONResponse(
        status_code=410,
        headers=_DEPRECATION_HEADERS,
        content={
            "status": "deprecated_operation_blocked",
            "path": path,
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "replacement": "/api/autonomous-paper/tick" if path.endswith("/tick") else "/api/autonomous-paper/status",
            "automatic_legacy_mutation": False,
        },
    )


def _remove_legacy_routes(app: FastAPI) -> None:
    targets = _DEPRECATED_READ_PATHS | _DEPRECATED_WRITE_PATHS | _DEPRECATED_PAGE_PATHS
    retained = []
    for route in app.router.routes:
        path = str(getattr(route, "path", ""))
        if path in targets:
            continue
        retained.append(route)
    app.router.routes[:] = retained


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
    """Replace legacy Virtual Account routes with canonical read adapters."""

    if getattr(app.state, "canonical_runtime_compat_api_installed", False):
        return
    app.state.canonical_runtime_compat_api_installed = True
    _remove_legacy_routes(app)
    _remove_legacy_startup(app)

    @app.middleware("http")
    async def canonical_demo_state(request: Request, call_next: Callable[[Request], Any]):
        if request.method == "GET" and request.url.path == "/api/demo/state":
            return JSONResponse(_compat_payload(app), headers=_DEPRECATION_HEADERS)
        return await call_next(request)

    @app.get("/api/paper-activity/state")
    def paper_activity_state() -> JSONResponse:
        return JSONResponse(_compat_payload(app), headers=_DEPRECATION_HEADERS)

    @app.get("/api/virtual-account/state")
    def virtual_account_state() -> JSONResponse:
        return JSONResponse(_compat_payload(app), headers=_DEPRECATION_HEADERS)

    @app.get("/api/demo/state/shared")
    def demo_state_shared() -> JSONResponse:
        return JSONResponse(_compat_payload(app), headers=_DEPRECATION_HEADERS)

    @app.get("/api/paper-activity/trades")
    def paper_activity_trades() -> JSONResponse:
        payload = _compat_payload(app)
        return JSONResponse(
            {
                "status": payload["status"],
                "deprecated": True,
                "replacement": "/api/autonomous-paper/status",
                "source_of_truth": payload["source_of_truth"],
                "summary": payload["summary"],
                "trades": payload["trades"],
            },
            headers=_DEPRECATION_HEADERS,
        )

    @app.get("/api/virtual-account/trades")
    def virtual_account_trades() -> JSONResponse:
        return paper_activity_trades()

    @app.post("/api/paper-activity/tick")
    def paper_activity_tick() -> dict[str, Any]:
        loop = _loop(app)
        loop.tick()
        return {
            **_snapshot(app),
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "legacy_route_deprecated": True,
        }

    @app.post("/api/virtual-account/tick")
    def virtual_account_tick() -> dict[str, Any]:
        return paper_activity_tick()

    @app.post("/api/paper-activity/catch-up")
    def paper_activity_catch_up() -> JSONResponse:
        return _deprecated_write("/api/paper-activity/catch-up")

    @app.post("/api/virtual-account/catch-up")
    def virtual_account_catch_up() -> JSONResponse:
        return _deprecated_write("/api/virtual-account/catch-up")

    @app.post("/api/paper-activity/reset")
    def paper_activity_reset() -> JSONResponse:
        return _deprecated_write("/api/paper-activity/reset")

    @app.get("/paper-activity", response_class=HTMLResponse)
    def paper_activity_page() -> HTMLResponse:
        return _canonical_page(app)

    @app.get("/virtual-account", response_class=HTMLResponse)
    def virtual_account_page() -> HTMLResponse:
        return _canonical_page(app)


def _canonical_page(app: FastAPI) -> HTMLResponse:
    payload = _compat_payload(app)
    summary = payload["summary"]
    body = "".join(
        f"<li><b>{escape(str(key))}</b>: {escape(str(value))}</li>"
        for key, value in summary.items()
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
