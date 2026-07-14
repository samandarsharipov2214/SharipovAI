"""Shared domain models for backtest, paper and future testnet execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class MarketEvent:
    timestamp_ms: int
    symbol: str
    bid: float
    ask: float
    source: str = "historical"
    volume: float | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class Signal:
    side: Side
    requested_risk_percent: float = 1.0
    stop_loss_percent: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_notional: float
    entry_fee: float
    opened_at_ms: int
    correlation_group: str


@dataclass(frozen=True, slots=True)
class Fill:
    timestamp_ms: int
    symbol: str
    side: Side
    quantity: float
    reference_price: float
    execution_price: float
    notional: float
    fee: float
    slippage_cost: float
    realized_pnl: float
    reason: str


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    timestamp_ms: int
    cash: float
    equity: float
    realized_pnl: float
    total_fees: float
    positions: dict[str, Position]


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    reserve_percent: float = 20.0
    max_total_exposure_percent: float = 80.0
    max_position_percent: float = 20.0
    max_correlated_exposure_percent: float = 35.0
    max_risk_per_trade_percent: float = 1.0
    max_open_positions: int = 5
    force_close_at_end: bool = True


@dataclass(frozen=True, slots=True)
class BacktestResult:
    initial_cash: float
    ending_equity: float
    net_pnl: float
    return_percent: float
    max_drawdown_percent: float
    total_fees: float
    total_slippage_cost: float
    trade_count: int
    winning_closed_trades: int
    losing_closed_trades: int
    fills: tuple[Fill, ...] = field(default_factory=tuple)
    equity_curve: tuple[tuple[int, float], ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "Fill",
    "MarketEvent",
    "PortfolioSnapshot",
    "Position",
    "Side",
    "Signal",
]
