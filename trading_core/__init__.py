"""Canonical domain layer shared by strategy research and execution simulation."""
from .backtest import EventDrivenBacktester, Strategy
from .costs import ExecutionCost, ExecutionCostModel
from .models import (
    BacktestConfig,
    BacktestResult,
    Fill,
    MarketEvent,
    PortfolioSnapshot,
    Position,
    Side,
    Signal,
)

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "EventDrivenBacktester",
    "ExecutionCost",
    "ExecutionCostModel",
    "Fill",
    "MarketEvent",
    "PortfolioSnapshot",
    "Position",
    "Side",
    "Signal",
    "Strategy",
]
