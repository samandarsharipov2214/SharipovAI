"""FastAPI endpoints for verified read-only market data and order previews."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from config.feature_flags import is_feature_enabled
from exchange_connector.bybit_instrument_rules import (
    BybitInstrumentRulesService,
    InstrumentRulesUnavailable,
)
from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker
from exchange_connector.market_data import MarketDataService, MarketDataUnavailable
from exchange_connector.multi_exchange_consensus import ConsensusUnavailable, MultiExchangeConsensus
from exchange_connector.order_preview import OrderPreviewError, build_order_preview


_MANUAL_RULE_FIELDS = {"tick_size", "qty_step", "min_qty", "min_notional"}


def install_market_data_api(app: FastAPI) -> None:
    if getattr(app.state, "market_data_api_installed", False):
        return
    app.state.market_data_api_installed = True
    app.state.market_data_service = MarketDataService()
    app.state.market_consensus = MultiExchangeConsensus(app.state.market_data_service)
    app.state.bybit_instrument_rules = BybitInstrumentRulesService()
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

    @app.get("/api/market/consensus/{symbol}")
    def market_consensus(symbol: str) -> dict[str, Any]:
        if not is_feature_enabled("multi_exchange_consensus"):
            raise HTTPException(
                status_code=503,
                detail={"status": "disabled", "verified": False, "synthetic_fallback_used": False},
            )
        try:
            quote = app.state.market_consensus.quote(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ConsensusUnavailable as exc:
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

    @app.get("/api/market/instrument-rules/{category}/{symbol}")
    def instrument_rules(category: str, symbol: str) -> dict[str, Any]:
        try:
            rules = app.state.bybit_instrument_rules.get(symbol, category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InstrumentRulesUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "unavailable", "verified": False, "message": str(exc)},
            ) from exc
        return {"status": "verified", "verified": True, **rules.to_dict()}

    @app.post("/api/trading/order-preview")
    def order_preview(payload: dict[str, Any]) -> dict[str, Any]:
        if not is_feature_enabled("bybit_preview_engine"):
            raise HTTPException(status_code=503, detail={"status": "disabled", "executed": False})
        manual = sorted(_MANUAL_RULE_FIELDS.intersection(payload))
        if manual:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "blocked",
                    "executed": False,
                    "message": f"manual instrument rules are forbidden: {', '.join(manual)}",
                },
            )
        try:
            category = str(payload.get("category", "spot")).strip().lower()
            rules = app.state.bybit_instrument_rules.get(payload.get("symbol"), category)
            merged = {**payload, **rules.preview_fields()}
            preview = build_order_preview(merged)
        except (OrderPreviewError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "blocked", "executed": False, "message": str(exc)},
            ) from exc
        except InstrumentRulesUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "blocked", "executed": False, "message": str(exc)},
            ) from exc
        return {
            "status": "preview",
            "executed": False,
            "instrument_rules": rules.to_dict(),
            **preview.to_dict(),
        }

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
