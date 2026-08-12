"""Canonical domain layer shared by strategy research and execution simulation."""
from .alpha_experiment import AlphaExperiment
from .alpha_strategies import RegimeFilteredBreakoutConfig, RegimeFilteredBreakoutStrategy
from .alpha_validation import (
    AlphaAcceptanceCriteria,
    AlphaRunMetrics,
    AlphaValidationReport,
    AlphaValidationWindow,
    AlphaVerdict,
    alpha_metrics,
    backtest_cost_config,
    backtest_risk_config,
    run_preregistered_alpha_validation,
    sha256_file,
)
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
from .paper_broker import PaperBrokerConfig, RestartSafePaperBroker
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
    "AlphaAcceptanceCriteria",
    "AlphaExperiment",
    "AlphaRunMetrics",
    "AlphaValidationReport",
    "AlphaValidationWindow",
    "AlphaVerdict",
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
    "PaperBrokerConfig",
    "PortfolioSnapshot",
    "Position",
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
    "TrendFollowingStrategy",
    "WalkForwardBacktester",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindowResult",
    "alpha_metrics",
    "backtest_cost_config",
    "backtest_risk_config",
    "compare_strategy_to_benchmarks",
    "evaluate_strategy_suite",
    "run_benchmark_suite",
    "run_preregistered_alpha_validation",
    "sha256_file",
]
