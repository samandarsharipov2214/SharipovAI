"""Dashboard API endpoints for the safe exchange connector."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from exchange_connector import SafeExchangeConnector


def install_exchange_api(app: FastAPI) -> None:
    """Install safe exchange endpoints on a FastAPI app.

    The endpoints expose status and order previews only. Real order execution is
    intentionally not exposed here.
    """

    if getattr(app.state, "exchange_api_installed", False):
        return
    app.state.exchange_api_installed = True

    @app.get("/api/exchange/status")
    def exchange_status() -> dict[str, object]:
        """Return exchange connector safety status without exposing secrets."""

        return {"status": "ok", "exchange": SafeExchangeConnector().status().to_dict()}

    @app.post("/api/exchange/preview-order")
    def exchange_preview_order(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Return a commission-aware safe order preview."""

        data = payload or {}
        try:
            preview = SafeExchangeConnector().preview_order(
                symbol=str(data.get("symbol", "BTCUSDT")),
                side=str(data.get("side", "BUY")),
                quantity=data.get("quantity", 0.1),
                price=data.get("price", 100.0),
                expected_exit_price=data.get("expected_exit_price"),
                fee_rate=data.get("fee_rate"),
            )
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "ok", "preview": preview.to_dict()}
