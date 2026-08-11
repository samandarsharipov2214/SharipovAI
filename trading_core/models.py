"""Shared domain models for backtest, paper and future Testnet execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One immutable market observation available to a strategy at one timestamp."""

    timestamp_ms: int
    symbol: str
    bid: float
    ask: float
    source: str = "historical"
    volume: float | None = None
    funding_rate: float = 0.0
    funding_interval_hours: float = 8.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class Signal:
    side: Side
    requested_risk_percent: float = 1.0
    stop_loss_percent: float = 1.0
    reason: str = ""
    liquidity_role: str = "taker"


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_notional: float
    entry_fee: float
    opened_at_ms: int
    correlation_group: str
    funding_paid: float = 0.0


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
    liquidity_role: str = "taker"
    spread_cost: float = 0.0
    participation_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class FundingPayment:
    timestamp_ms: int
    symbol: str
    rate: float
    notional: float
    interval_fraction: float
    amount: float


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    timestamp_ms: int
    cash: float
    equity: float
    realized_pnl: float
    total_fees: float
    positions: dict[str, Position]
    total_funding_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    market_impact_bps: float = 15.0
    max_participation_rate: float = 0.10
    reserve_percent: float = 20.0
    max_total_exposure_percent: float = 80.0
    max_position_percent: float = 20.0
    max_correlated_exposure_percent: float = 35.0
    max_risk_per_trade_percent: float = 1.0
    max_open_positions: int = 5
    minimum_notional: float = 25.0
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
    total_funding_cost: float = 0.0
    gross_trading_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    exposure_time_percent: float = 0.0
    funding_payments: tuple[FundingPayment, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    train_events: int = 500
    test_events: int = 100
    step_events: int = 100
    anchored: bool = False
    chain_capital: bool = True
    minimum_windows: int = 2


@dataclass(frozen=True, slots=True)
class WalkForwardWindowResult:
    window_index: int
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    train_event_count: int
    test_event_count: int
    result: BacktestResult


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: tuple[WalkForwardWindowResult, ...]
    initial_cash: float
    ending_equity: float
    net_pnl: float
    return_percent: float
    profitable_windows: int
    profitable_window_percent: float
    max_drawdown_percent: float
    total_fees: float
    total_slippage_cost: float
    total_funding_cost: float
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "Fill",
    "FundingPayment",
    "MarketEvent",
    "PortfolioSnapshot",
    "Position",
    "Side",
    "Signal",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindowResult",
]
