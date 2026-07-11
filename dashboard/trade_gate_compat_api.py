"""Guaranteed Trade Gate routes for app factories where feature installation failed."""
from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from trading_intelligence import trade_gate


def install_trade_gate_compat_api(app: FastAPI) -> None:
    if getattr(app.state, "trade_gate_compat_api_installed", False):
        return
    app.state.trade_gate_compat_api_installed = True

    existing_get = any(getattr(route, "path", None) == "/api/trade-gate" and "GET" in (getattr(route, "methods", set()) or set()) for route in app.routes)
    existing_post = any(getattr(route, "path", None) == "/api/trade-gate" and "POST" in (getattr(route, "methods", set()) or set()) for route in app.routes)

    if not existing_get:
        @app.get("/api/trade-gate")
        def trade_gate_get() -> dict[str, Any]:
            return trade_gate()

    if not existing_post:
        @app.post("/api/trade-gate")
        def trade_gate_post(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
            return trade_gate(payload or {})


__all__: tuple[str, ...] = ("install_trade_gate_compat_api",)
