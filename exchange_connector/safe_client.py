"""Safety-first exchange connector.

This connector never sends real orders by default. It reads public configuration,
checks whether credentials are configured, and creates order previews that count
commissions as costs/losses before any real integration is allowed.
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
        expected_exit_price: Any | None = None,
        fee_rate: Any | None = None,
    ) -> ExchangeOrderPreview:
        """Build a pre-trade order preview with commission included as loss/cost.

        If ``expected_exit_price`` is provided, AI receives both gross result and
        net result after commissions. This prevents false profitable signals when
        commissions are larger than the expected move.
        """

        normalized_side = str(side).strip().upper()
        if normalized_side not in _SAFE_SIDES:
            raise ValueError("side must be BUY or SELL")

        clean_quantity = _positive_float(quantity, "quantity")
        clean_price = _positive_float(price, "price")
        clean_exit_price = None
        if expected_exit_price is not None:
            clean_exit_price = _positive_float(expected_exit_price, "expected_exit_price")
        clean_fee_rate = _safe_fee_rate(self.config.default_fee_rate if fee_rate is None else fee_rate)
        notional = clean_quantity * clean_price
        entry_fee = notional * clean_fee_rate
        exit_notional = clean_quantity * clean_exit_price if clean_exit_price is not None else 0.0
        expected_exit_fee = exit_notional * clean_fee_rate if clean_exit_price is not None else 0.0
        total_fees = entry_fee + expected_exit_fee
        total_cost = notional + entry_fee if normalized_side == "BUY" else max(entry_fee, 0.0)
        gross_result = _gross_result(
            side=normalized_side,
            quantity=clean_quantity,
            entry_price=clean_price,
            expected_exit_price=clean_exit_price,
        )
        net_result = None if gross_result is None else gross_result - total_fees
        commission_drag = None if gross_result is None else total_fees
        break_even_price = _break_even_price(
            side=normalized_side,
            price=clean_price,
            fee_rate=clean_fee_rate,
        )
        execution_allowed = self.status().can_execute_orders
        warning = _warning(
            execution_allowed=execution_allowed,
            gross_result=gross_result,
            net_result=net_result,
            total_fees=total_fees,
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
            entry_fee=entry_fee,
            expected_exit_price=clean_exit_price,
            expected_exit_fee=expected_exit_fee,
            total_fees=total_fees,
            total_cost=total_cost,
            gross_result=gross_result,
            net_result_after_fees=net_result,
            commission_drag=commission_drag,
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


def _gross_result(
    *,
    side: str,
    quantity: float,
    entry_price: float,
    expected_exit_price: float | None,
) -> float | None:
    """Return gross result before commissions."""

    if expected_exit_price is None:
        return None
    if side == "BUY":
        return (expected_exit_price - entry_price) * quantity
    return (entry_price - expected_exit_price) * quantity


def _break_even_price(*, side: str, price: float, fee_rate: float) -> float:
    """Return approximate break-even price after round-trip commissions."""

    round_trip_fee = fee_rate * 2
    if side == "BUY":
        return price * (1 + round_trip_fee)
    return max(price * (1 - round_trip_fee), 0.0)


def _warning(
    *,
    execution_allowed: bool,
    gross_result: float | None,
    net_result: float | None,
    total_fees: float,
) -> str:
    """Return a safety warning for AI and UI."""

    if gross_result is not None and net_result is not None:
        if gross_result > 0 and net_result <= 0:
            return "Commission turns this gross profit into a net loss. Do not trade."
        if total_fees > abs(gross_result):
            return "Commission is larger than the expected move. Avoid this trade."
    if not execution_allowed:
        return "Real execution is blocked. This is only an order preview."
    return "Live execution is enabled; require manual risk confirmation before sending."


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
