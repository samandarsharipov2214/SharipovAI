"""Admin-only runtime API for the read-only private Bybit order stream."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from autonomous_trading import ExecutionJournal
from exchange_connector.bybit_private_order_ws import BybitPrivateOrderWebSocket

from .admin_guard import install_sensitive_api_guard, require_admin


def install_private_order_ws_api(
    app: FastAPI,
    *,
    worker: BybitPrivateOrderWebSocket | None = None,
    journal: ExecutionJournal | None = None,
) -> None:
    if getattr(app.state, "private_order_ws_api_installed", False):
        return
    app.state.private_order_ws_api_installed = True
    install_sensitive_api_guard(app)
    app.state.private_order_ws = worker or BybitPrivateOrderWebSocket()
    app.state.private_order_ws_journal = journal or ExecutionJournal()
    _register_event(app, "startup", app.state.private_order_ws.start)
    _register_event(app, "shutdown", app.state.private_order_ws.stop)

    @app.get("/api/exchange/private-order-ws/status")
    def private_order_ws_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _mapping(app.state.private_order_ws.status(), "private order WebSocket status")

    @app.get("/api/exchange/private-order-ws/snapshot")
    def private_order_ws_snapshot(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            return _mapping(app.state.private_order_ws.snapshot(), "private order WebSocket snapshot")
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "message": f"{type(exc).__name__}: {exc}"}) from exc

    @app.post("/api/exchange/private-order-ws/reconcile")
    def private_order_ws_reconcile(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            result = app.state.private_order_ws.reconcile(app.state.private_order_ws_journal.load())
            return _mapping(result, "private order WebSocket reconciliation")
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "message": f"{type(exc).__name__}: {exc}"}) from exc


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must return an object")
    return value


def _register_event(app: FastAPI, event: str, handler: Any) -> None:
    add_event_handler = getattr(app, "add_event_handler", None)
    if callable(add_event_handler):
        add_event_handler(event, handler)
        return
    handlers = getattr(getattr(app, "router", None), f"on_{event}", None)
    if isinstance(handlers, list):
        handlers.append(handler)
        return
    raise RuntimeError(f"FastAPI lifecycle handler registration unavailable for {event}")


__all__ = ["install_private_order_ws_api"]
