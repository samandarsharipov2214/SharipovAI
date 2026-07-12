"""FastAPI endpoints for verified read-only market data and order previews."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import Body, FastAPI, HTTPException, Query

from config.feature_flags import is_feature_enabled
from exchange_connector.bybit_instrument_rules import (
    BybitInstrumentRulesService,
    InstrumentRulesUnavailable,
)
from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker
from exchange_connector.market_data import MarketDataService, MarketDataUnavailable, normalize_symbol
from exchange_connector.multi_exchange_consensus import ConsensusUnavailable, MultiExchangeConsensus
from exchange_connector.order_preview import OrderPreviewError, build_order_preview

_BYBIT_MARKET_URL = "https://api.bybit.com/v5/market"
_ALLOWED_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"}
_ALLOWED_CATEGORIES = {"spot", "linear", "inverse"}
_TRUTHY = {"1", "true", "yes", "on"}


def _configure_public_stream_feature() -> None:
    """Map the public market switch once without overriding an explicit feature value."""
    if "FEATURE_BYBIT_WEBSOCKET" in os.environ:
        return
    if os.getenv("MARKET_STREAM_ENABLED", "").strip().lower() in _TRUTHY:
        os.environ["FEATURE_BYBIT_WEBSOCKET"] = "1"


def install_market_data_api(app: FastAPI) -> None:
    if getattr(app.state, "market_data_api_installed", False):
        return
    _configure_public_stream_feature()
    app.state.market_data_api_installed = True
    app.state.market_data_service = MarketDataService()
    app.state.bybit_websocket_worker = BybitWebSocketWorker()
    app.state.multi_exchange_consensus = MultiExchangeConsensus(app.state.market_data_service)
    app.state.bybit_instrument_rules = BybitInstrumentRulesService()
    _register_lifecycle_handler(app, "startup", app.state.bybit_websocket_worker.start)
    _register_lifecycle_handler(app, "shutdown", app.state.bybit_websocket_worker.stop)

    @app.get("/api/market/quote/{symbol}")
    def market_quote(symbol: str) -> dict[str, Any]:
        try:
            quote = app.state.market_data_service.quote(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MarketDataUnavailable as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "synthetic_fallback_used": False, "message": str(exc)}) from exc
        return {**quote.to_dict(), "synthetic_fallback_used": False}

    @app.get("/api/market/candles/{symbol}")
    def market_candles(
        symbol: str,
        interval: str = Query(default="15"),
        limit: int = Query(default=200, ge=20, le=1000),
        category: str = Query(default="spot"),
    ) -> dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        clean_interval = str(interval).upper()
        clean_category = str(category).lower()
        if clean_interval not in _ALLOWED_INTERVALS:
            raise HTTPException(status_code=400, detail="Неподдерживаемый интервал свечей")
        if clean_category not in _ALLOWED_CATEGORIES:
            raise HTTPException(status_code=400, detail="Неподдерживаемый тип рынка")
        try:
            payload = app.state.market_data_service.get_json(
                f"{_BYBIT_MARKET_URL}/kline",
                params={"category": clean_category, "symbol": clean_symbol, "interval": clean_interval, "limit": str(limit)},
            )
            if payload.get("retCode") != 0:
                raise ValueError(payload.get("retMsg") or "Bybit вернул ошибку")
            rows = payload.get("result", {}).get("list", [])
            candles = [
                {
                    "time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "turnover": float(row[6]),
                }
                for row in reversed(rows)
                if isinstance(row, list) and len(row) >= 7
            ]
            if not candles:
                raise ValueError("Bybit не вернул свечи")
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "synthetic_fallback_used": False, "message": str(exc)}) from exc
        return {
            "status": "ok",
            "verified": True,
            "synthetic_fallback_used": False,
            "source": "Bybit",
            "symbol": clean_symbol,
            "category": clean_category,
            "interval": clean_interval,
            "received_at": datetime.now(UTC).isoformat(),
            "candles": candles,
        }

    @app.get("/api/market/orderbook/{symbol}")
    def market_orderbook(
        symbol: str,
        limit: int = Query(default=25, ge=1, le=200),
        category: str = Query(default="spot"),
    ) -> dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        clean_category = str(category).lower()
        if clean_category not in _ALLOWED_CATEGORIES:
            raise HTTPException(status_code=400, detail="Неподдерживаемый тип рынка")
        try:
            payload = app.state.market_data_service.get_json(
                f"{_BYBIT_MARKET_URL}/orderbook",
                params={"category": clean_category, "symbol": clean_symbol, "limit": str(limit)},
            )
            if payload.get("retCode") != 0:
                raise ValueError(payload.get("retMsg") or "Bybit вернул ошибку")
            result = payload.get("result", {})
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "message": str(exc)}) from exc
        return {
            "status": "ok", "verified": True, "source": "Bybit", "symbol": clean_symbol,
            "received_at": datetime.now(UTC).isoformat(), "bids": result.get("b", []), "asks": result.get("a", []),
        }

    @app.get("/api/market/trades/{symbol}")
    def market_recent_trades(
        symbol: str,
        limit: int = Query(default=50, ge=1, le=1000),
        category: str = Query(default="spot"),
    ) -> dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        clean_category = str(category).lower()
        if clean_category not in _ALLOWED_CATEGORIES:
            raise HTTPException(status_code=400, detail="Неподдерживаемый тип рынка")
        try:
            payload = app.state.market_data_service.get_json(
                f"{_BYBIT_MARKET_URL}/recent-trade",
                params={"category": clean_category, "symbol": clean_symbol, "limit": str(limit)},
            )
            if payload.get("retCode") != 0:
                raise ValueError(payload.get("retMsg") or "Bybit вернул ошибку")
            rows = payload.get("result", {}).get("list", [])
            trades = [
                {
                    "time": int(row.get("time", 0)),
                    "price": float(row["price"]),
                    "size": float(row["size"]),
                    "side": str(row.get("side", "")),
                    "is_block_trade": bool(row.get("isBlockTrade", False)),
                }
                for row in rows
                if isinstance(row, dict) and row.get("price") not in (None, "") and row.get("size") not in (None, "")
            ]
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "synthetic_fallback_used": False, "message": str(exc)}) from exc
        return {
            "status": "ok",
            "verified": True,
            "synthetic_fallback_used": False,
            "source": "Bybit",
            "symbol": clean_symbol,
            "category": clean_category,
            "received_at": datetime.now(UTC).isoformat(),
            "trades": trades,
        }

    @app.get("/api/market/bybit-websocket/status")
    def bybit_websocket_status() -> dict[str, Any]:
        return app.state.bybit_websocket_worker.status()

    @app.get("/api/market/bybit-websocket/quote/{symbol}")
    def bybit_websocket_quote(symbol: str) -> dict[str, Any]:
        try:
            quote = app.state.bybit_websocket_worker.quote(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "synthetic_fallback_used": False, "message": str(exc)}) from exc
        return {**quote, "verified": True, "synthetic_fallback_used": False}

    @app.get("/api/market/consensus/{symbol}")
    def market_consensus(symbol: str) -> dict[str, Any]:
        if not is_feature_enabled("multi_exchange_consensus"):
            raise HTTPException(status_code=503, detail={"status": "disabled", "verified": False, "synthetic_fallback_used": False})
        try:
            quote = app.state.multi_exchange_consensus.quote(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ConsensusUnavailable as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "synthetic_fallback_used": False, "message": str(exc)}) from exc
        return {**quote.to_dict(), "synthetic_fallback_used": False}

    @app.get("/api/market/instrument-rules/{category}/{symbol}")
    def instrument_rules(category: str, symbol: str) -> dict[str, Any]:
        try:
            rules = app.state.bybit_instrument_rules.get(symbol, category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InstrumentRulesUnavailable as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "verified": False, "message": str(exc)}) from exc
        return {**rules.to_dict(), "verified": True}

    @app.post("/api/trading/order-preview")
    def order_preview(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        if not is_feature_enabled("bybit_preview_engine"):
            raise HTTPException(status_code=503, detail={"status": "disabled", "executed": False})
        data = payload or {}
        try:
            symbol = str(data.get("symbol", ""))
            category = str(data.get("category", "spot"))
            rules = app.state.bybit_instrument_rules.get(symbol, category)
            preview = build_order_preview(data, rules)
        except (ValueError, OrderPreviewError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InstrumentRulesUnavailable as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "executed": False, "message": str(exc)}) from exc
        return {"status": "ok", "preview": preview.to_dict()}


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
