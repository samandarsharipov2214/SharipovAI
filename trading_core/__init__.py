"""Canonical domain layer shared by strategy research and execution simulation."""
from .alpha_experiment import AlphaExperiment
from .alpha_strategies import RegimeFilteredBreakoutConfig, RegimeFilteredBreakoutStrategy
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
from .cost_scenarios import (
    TransactionCostScenario,
    TransactionCostScenarioResult,
    evaluate_transaction_cost_scenarios,
)
from .costs import ExecutionCost, ExecutionCostModel, RoundTripCost
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
from .paper_broker import PaperBrokerConfig, RestartSafePaperBroker
from .performance_statistics import PerformanceStatistics, summarize_performance
from .purged_walk_forward import PurgedWalkForwardBacktester, PurgedWalkForwardConfig
from .strategies import (
    BreakoutStrategy,
    BuyAndHoldStrategy,
    MeanReversionStrategy,
    TrendFollowingStrategy,
)
from .strategy_suite import (
    StrategyComparison,
    StrategySuiteConfig,
    StrategySuiteReport,
    evaluate_strategy_suite,
)

__all__ = [
    "AlphaExperiment",
    "BacktestConfig",
    "BacktestResult",
    "BenchmarkEntry",
    "BenchmarkSuiteResult",
    "BreakoutStrategy",
    "BuyAndHoldStrategy",
    "EventDrivenBacktester",
    "ExecutionCost",
    "ExecutionCostModel",
    "RoundTripCost",
    "Fill",
    "FundingPayment",
    "MarketEvent",
    "MeanReversionStrategy",
    "PaperBrokerConfig",
    "PerformanceStatistics",
    "PortfolioSnapshot",
    "Position",
    "PurgedWalkForwardBacktester",
    "PurgedWalkForwardConfig",
    "RegimeFilteredBreakoutConfig",
    "RegimeFilteredBreakoutStrategy",
    "RestartSafePaperBroker",
    "Side",
    "Signal",
    "Strategy",
    "StrategyComparison",
    "StrategyFactory",
    "StrategySuiteConfig",
    "StrategySuiteReport",
    "TransactionCostScenario",
    "TransactionCostScenarioResult",
    "TrendFollowingStrategy",
    "WalkForwardBacktester",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindowResult",
    "compare_strategy_to_benchmarks",
    "evaluate_strategy_suite",
    "evaluate_transaction_cost_scenarios",
    "run_benchmark_suite",
    "summarize_performance",
]
