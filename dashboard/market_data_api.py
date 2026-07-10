"""FastAPI endpoints for verified read-only market data."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from exchange_connector.market_data import MarketDataService, MarketDataUnavailable


def install_market_data_api(app: FastAPI) -> None:
    if getattr(app.state, "market_data_api_installed", False):
        return
    app.state.market_data_api_installed = True
    app.state.market_data_service = MarketDataService()

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
