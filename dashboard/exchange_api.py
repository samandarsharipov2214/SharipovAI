"""Dashboard API endpoints for the safe exchange connector."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from exchange_connector import (
    SafeExchangeConnector,
    ai_cost_report,
    best_trade_venue,
    borrow_table,
    estimate_borrow_cost,
    estimate_trade_cost,
    fee_table,
    vip_progress,
)


def install_exchange_api(app: FastAPI) -> None:
    """Install safe exchange endpoints on a FastAPI app.

    The endpoints expose status, cost intelligence, and order previews only.
    Real order execution is intentionally not exposed here.
    """

    if getattr(app.state, "exchange_api_installed", False):
        return
    app.state.exchange_api_installed = True

    @app.get("/api/exchange/status")
    def exchange_status() -> dict[str, object]:
        """Return exchange connector safety status without exposing secrets."""

        return {"status": "ok", "exchange": SafeExchangeConnector().status().to_dict()}

    @app.get("/api/exchange/costs")
    def exchange_costs() -> dict[str, object]:
        """Return Bybit fee, borrow, and AI cost-intelligence data."""

        return {"status": "ok", "costs": ai_cost_report()}

    @app.post("/api/exchange/costs/estimate")
    def estimate_costs(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Estimate fees, borrow interest, and best venue for a planned trade."""

        data = payload or {}
        notional = _safe_float(data.get("notional"), 500.0)
        product = str(data.get("product", "spot"))
        liquidity = str(data.get("liquidity", "taker"))
        vip_level = str(data.get("vip_level", "Обычный"))
        borrow_symbol = str(data.get("borrow_symbol", "USDT"))
        borrow_amount = _safe_float(data.get("borrow_amount"), 0.0)
        borrow_hours = _safe_float(data.get("borrow_hours"), 24.0)
        return {
            "status": "ok",
            "trade_cost": estimate_trade_cost(
                notional=notional,
                product=product,
                liquidity=liquidity,
                vip_level=vip_level,
            ),
            "borrow_cost": estimate_borrow_cost(borrow_symbol, borrow_amount, borrow_hours),
            "best_trade_venue": best_trade_venue(notional=notional, vip_level=vip_level),
            "vip_progress": vip_progress(data.get("vip_metrics") if isinstance(data.get("vip_metrics"), dict) else None),
        }

    @app.get("/api/exchange/fees")
    def exchange_fees() -> dict[str, object]:
        """Return seeded Bybit fee tables."""

        return {"status": "ok", "fees": fee_table()}

    @app.get("/api/exchange/borrow-rates")
    def exchange_borrow_rates() -> dict[str, object]:
        """Return seeded Bybit borrow rates sorted by cost."""

        return {"status": "ok", "borrow_rates": borrow_table()}

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


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
