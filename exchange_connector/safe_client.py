"""Safety-first exchange connector.

This module prepares SharipovAI for exchange integration without enabling real
trading by default. Commissions are always included in the order preview as a
cost/loss so AI decisions do not overstate profit.
"""

from __future__ import annotations

import os
from typing import Any

from .models import ExchangeConfig, ExchangeOrderPreview, ExchangeStatus

_SAFE_MODES = {"disabled", "sandbox", "live"}
_SAFE_SIDES = {"BUY", "SELL"}


class SafeExchangeConnector:
    """Exchange connector with hard safety gates around real execution."""

    def __init__(self, config: ExchangeConfig | None = None) -> None:
        """Initialize connector with optional explicit configuration."""

        self.config = config or load_exchange_config()

    def status(self) -> ExchangeStatus:
        """Return public exchange connector status without exposing secrets."""

        mode = self.config.mode
        keys_ready = self.config.api_key_configured and self.config.api_secret_configured
        can_read = mode in {"sandbox", "live"}
        can_preview = mode in {"sandbox", "live"}
        can_execute = mode == "live" and keys_ready and self.config.live_trading_enabled
        if mode == "disabled":
            message = "Exchange connector is disabled. Market reading and trading are blocked."
        elif can_execute:
            message = "Live trading gate is open. Use only after manual risk approval."
        else:
            message = "Safe mode: market reading/order preview allowed, real execution blocked."
        return ExchangeStatus(
            exchange_name=self.config.exchange_name,
            mode=mode,
            connected=can_read,
            can_read_market=can_read,
            can_preview_orders=can_preview,
            can_execute_orders=can_execute,
            live_trading_enabled=self.config.live_trading_enabled,
            api_key_configured=self.config.api_key_configured,
            api_secret_configured=self.config.api_secret_configured,
            message=message,
        )

    def preview_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Any,
        price: Any,
        fee_rate: Any | None = None,
    ) -> ExchangeOrderPreview:
        """Build a pre-trade order preview with commission included as loss/cost."""

        normalized_side = str(side).strip().upper()
        if normalized_side not in _SAFE_SIDES:
            raise ValueError("side must be BUY or SELL")

        clean_quantity = _positive_float(quantity, "quantity")
        clean_price = _positive_float(price, "price")
        clean_fee_rate = _safe_fee_rate(self.config.default_fee_rate if fee_rate is None else fee_rate)
        notional = clean_quantity * clean_price
        estimated_fee = notional * clean_fee_rate
        execution_allowed = self.status().can_execute_orders
        if normalized_side == "BUY":
            total_cost = notional + estimated_fee
            break_even_price = (notional + estimated_fee) / clean_quantity
        else:
            total_cost = max(notional - estimated_fee, 0.0)
            break_even_price = (notional - estimated_fee) / clean_quantity
        warning = (
            "Real execution is blocked. This is only an order preview."
            if not execution_allowed
            else "Live execution is enabled; require manual risk confirmation before sending."
        )
        return ExchangeOrderPreview(
            exchange_name=self.config.exchange_name,
            mode=self.config.mode,
            symbol=str(symbol).strip().upper() or "UNKNOWN",
            side=normalized_side,
            quantity=clean_quantity,
            price=clean_price,
            notional=notional,
            fee_rate=clean_fee_rate,
            estimated_fee=estimated_fee,
            total_cost=total_cost,
            break_even_price=break_even_price,
            commission_counted_as_loss=True,
            execution_allowed=execution_allowed,
            warning=warning,
        )

    def place_order(self, *_args: Any, **_kwargs: Any) -> None:
        """Block real order execution unless a future audited implementation is added."""

        raise RuntimeError(
            "Real exchange order execution is not implemented. "
            "Use preview_order() and Paper Trading until audited live execution is added."
        )


def load_exchange_config() -> ExchangeConfig:
    """Load safe exchange configuration from environment variables."""

    mode = os.getenv("EXCHANGE_MODE", "disabled").strip().lower()
    if mode not in _SAFE_MODES:
        mode = "disabled"
    return ExchangeConfig(
        exchange_name=os.getenv("EXCHANGE_NAME", "bybit").strip().lower() or "bybit",
        mode=mode,
        base_url=os.getenv("EXCHANGE_BASE_URL", "https://api.bybit.com").strip(),
        api_key_configured=bool(os.getenv("EXCHANGE_API_KEY", "").strip()),
        api_secret_configured=bool(os.getenv("EXCHANGE_API_SECRET", "").strip()),
        live_trading_enabled=_truthy(os.getenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")),
        default_fee_rate=_safe_fee_rate(os.getenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")),
    )


def _truthy(value: str) -> bool:
    """Return whether an environment flag is truthy."""

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _positive_float(value: Any, field_name: str) -> float:
    """Parse a strictly positive float."""

    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive number") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return parsed


def _safe_fee_rate(value: Any) -> float:
    """Parse a safe fee rate; invalid values fall back to 0.1%."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.001
    if parsed < 0:
        return 0.001
    return min(parsed, 0.05)
