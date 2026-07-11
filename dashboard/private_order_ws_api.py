"""Admin-only dashboard integration for the private Bybit order WebSocket.

The worker is installed at runtime but remains inert unless its existing
FEATURE_BYBIT_PRIVATE_ORDER_WS flag is explicitly enabled. These routes never
submit, amend, or cancel orders.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from autonomous_trading import ExecutionJournal
from exchange_connector import bybit_private_order_ws as private_order_ws_module

from .admin_guard import install_sensitive_api_guard, require_admin


def install_private_order_ws_api(
    app: FastAPI,
    *,
    worker: Any | None = None,
    journal: ExecutionJournal | None = None,
) -> None:
    """Install protected status, snapshot, and reconciliation endpoints once."""
    if getattr(app.state, "private_order_ws_api_installed", False):
        return
    app.state.private_order_ws_api_installed = True
    install_sensitive_api_guard(app)
    app.state.private_order_ws = worker or _build_worker()
    app.state.private_order_ws_journal = journal or ExecutionJournal()

    _register_lifecycle_handler(app, "startup", app.state.private_order_ws.start)
    _register_lifecycle_handler(app, "shutdown", app.state.private_order_ws.stop)

    @app.get("/api/exchange/private-order-ws/status")
    def private_order_ws_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _mapping(app.state.private_order_ws.status(), "private order websocket status")

    @app.get("/api/exchange/private-order-ws/snapshot")
    def private_order_ws_snapshot(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            return _mapping(app.state.private_order_ws.snapshot(), "private order websocket snapshot")
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "unavailable", "message": str(exc)},
            ) from exc

    @app.post("/api/exchange/private-order-ws/reconcile")
    def private_order_ws_reconcile(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            journal_data = app.state.private_order_ws_journal.load()
            result = app.state.private_order_ws.reconcile(journal_data)
            return _mapping(result, "private order websocket reconciliation")
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "unavailable", "message": str(exc)},
            ) from exc


def _build_worker() -> Any:
    """Resolve the worker by capability, avoiding a second implementation."""
    candidates: list[type[Any]] = []
    for value in vars(private_order_ws_module).values():
        if not isinstance(value, type):
            continue
        if all(callable(getattr(value, name, None)) for name in ("start", "stop", "status", "snapshot", "reconcile")):
            candidates.append(value)
    if len(candidates) != 1:
        raise RuntimeError("private Bybit order WebSocket worker contract is unavailable or ambiguous")
    return candidates[0]()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must return an object")
    return value


def _register_lifecycle_handler(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
    """Register lifecycle handlers across supported FastAPI/Starlette versions."""
    legacy = getattr(app, "add_event_handler", None)
    if callable(legacy):
        legacy(event, handler)
        return
    router = getattr(app, "router", None)
    handlers = getattr(router, f"on_{event}", None) if router is not None else None
    if isinstance(handlers, list):
        handlers.append(handler)
        return
    if event == "startup":
        handler()
