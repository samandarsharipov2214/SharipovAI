"""Canonical domain layer shared by strategy research and execution simulation."""
from .backtest import (
    EventDrivenBacktester,
    Strategy,
    StrategyFactory,
    WalkForwardBacktester,
)
from .benchmarks import (
    BenchmarkEntry,
    BenchmarkSuiteResult,
    compare_strategy_to_benchmarks,
    run_benchmark_suite,
)
from .costs import ExecutionCost, ExecutionCostModel
from .models import (
    BacktestConfig,
    BacktestResult,
    Fill,
    FundingPayment,
    MarketEvent,
    PortfolioSnapshot,
    Position,
    Side,
    Signal,
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindowResult,
)
from .strategies import (
    BreakoutStrategy,
    BuyAndHoldStrategy,
    MeanReversionStrategy,
    TrendFollowingStrategy,
)

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BenchmarkEntry",
    "BenchmarkSuiteResult",
    "BreakoutStrategy",
    "BuyAndHoldStrategy",
    "EventDrivenBacktester",
    "ExecutionCost",
    "ExecutionCostModel",
    "Fill",
    "FundingPayment",
    "MarketEvent",
    "MeanReversionStrategy",
    "PortfolioSnapshot",
    "Position",
    "Side",
    "Signal",
    "Strategy",
    "StrategyFactory",
    "TrendFollowingStrategy",
    "WalkForwardBacktester",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindowResult",
    "compare_strategy_to_benchmarks",
    "run_benchmark_suite",
]
