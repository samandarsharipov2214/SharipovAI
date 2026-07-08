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
    estimated_fee: float
    total_cost: float
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
            "estimated_fee": self.estimated_fee,
            "total_cost": self.total_cost,
            "break_even_price": self.break_even_price,
            "commission_counted_as_loss": self.commission_counted_as_loss,
            "execution_allowed": self.execution_allowed,
            "warning": self.warning,
        }
