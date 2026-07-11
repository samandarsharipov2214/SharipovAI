"""FastAPI endpoints for verified read-only market data."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker
from exchange_connector.market_data import MarketDataService, MarketDataUnavailable


def install_market_data_api(app: FastAPI) -> None:
    if getattr(app.state, "market_data_api_installed", False):
        return
    app.state.market_data_api_installed = True
    app.state.market_data_service = MarketDataService()
    app.state.bybit_websocket_worker = BybitWebSocketWorker()
    _register_lifecycle_handler(app, "startup", app.state.bybit_websocket_worker.start)
    _register_lifecycle_handler(app, "shutdown", app.state.bybit_websocket_worker.stop)

    @app.get("/api/market/quote/{symbol}")
    def market_quote(symbol: str) -> dict[str, Any]:
        try:
            quote = app.state.market_data_service.quote(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MarketDataUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "unavailable",
                    "verified": False,
                    "synthetic_fallback_used": False,
                    "message": str(exc),
                },
            ) from exc
        return {**quote.to_dict(), "synthetic_fallback_used": False}

    @app.get("/api/market/websocket/status")
    def websocket_status() -> dict[str, Any]:
        return app.state.bybit_websocket_worker.status()

    @app.get("/api/market/websocket/quote/{symbol}")
    def websocket_quote(symbol: str) -> dict[str, Any]:
        try:
            quote = app.state.bybit_websocket_worker.quote(symbol)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "unavailable",
                    "verified": False,
                    "synthetic_fallback_used": False,
                    "message": str(exc),
                },
            ) from exc
        return {**quote, "verified": True, "synthetic_fallback_used": False}


def _register_lifecycle_handler(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
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
