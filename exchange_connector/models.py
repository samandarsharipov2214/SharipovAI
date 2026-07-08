"""Models for the safe exchange connector."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeConfig:
    """Environment-derived exchange configuration without secret values."""

    exchange_name: str
    mode: str
    base_url: str
    api_key_configured: bool
    api_secret_configured: bool
    live_trading_enabled: bool
    default_fee_rate: float


@dataclass(frozen=True)
class ExchangeStatus:
    """Public safety status of the exchange connector."""

    exchange_name: str
    mode: str
    connected: bool
    can_read_market: bool
    can_preview_orders: bool
    can_execute_orders: bool
    live_trading_enabled: bool
    api_key_configured: bool
    api_secret_configured: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable status."""

        return {
            "exchange_name": self.exchange_name,
            "mode": self.mode,
            "connected": self.connected,
            "can_read_market": self.can_read_market,
            "can_preview_orders": self.can_preview_orders,
            "can_execute_orders": self.can_execute_orders,
            "live_trading_enabled": self.live_trading_enabled,
            "api_key_configured": self.api_key_configured,
            "api_secret_configured": self.api_secret_configured,
            "message": self.message,
        }


@dataclass(frozen=True)
class ExchangeOrderPreview:
    """Pre-trade calculation that includes commissions as costs/losses."""

    exchange_name: str
    mode: str
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    fee_rate: float
    entry_fee: float
    expected_exit_price: float | None
    expected_exit_fee: float
    total_fees: float
    total_cost: float
    gross_result: float | None
    net_result_after_fees: float | None
    commission_drag: float | None
    break_even_price: float
    commission_counted_as_loss: bool
    execution_allowed: bool
    warning: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable preview."""

        return {
            "exchange_name": self.exchange_name,
            "mode": self.mode,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "notional": self.notional,
            "fee_rate": self.fee_rate,
            "entry_fee": self.entry_fee,
            "expected_exit_price": self.expected_exit_price,
            "expected_exit_fee": self.expected_exit_fee,
            "total_fees": self.total_fees,
            "total_cost": self.total_cost,
            "gross_result": self.gross_result,
            "net_result_after_fees": self.net_result_after_fees,
            "commission_drag": self.commission_drag,
            "break_even_price": self.break_even_price,
            "commission_counted_as_loss": self.commission_counted_as_loss,
            "execution_allowed": self.execution_allowed,
            "warning": self.warning,
        }
