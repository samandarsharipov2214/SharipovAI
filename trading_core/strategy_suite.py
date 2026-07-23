"""Deterministic strategy suite and benchmark comparison.

This module does not promote or execute a strategy. It runs identical event and
cost assumptions for Buy-and-Hold, Trend, Breakout and Mean Reversion and emits
an evidence table suitable for champion/challenger review.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .backtest import EventDrivenBacktester
from .models import BacktestConfig, BacktestResult, MarketEvent
from .strategies import (
    BreakoutStrategy,
    BuyAndHoldStrategy,
    MeanReversionStrategy,
    TrendFollowingStrategy,
)


@dataclass(frozen=True, slots=True)
class StrategySuiteConfig:
    trend_short_window: int = 20
    trend_long_window: int = 50
    trend_buffer_percent: float = 0.10
    breakout_entry_window: int = 20
    breakout_exit_window: int = 10
    breakout_buffer_percent: float = 0.10
    mean_reversion_window: int = 30
    mean_reversion_entry_zscore: float = 1.75
    mean_reversion_exit_zscore: float = 0.25
    minimum_trades: int = 2
    maximum_drawdown_percent: float = 15.0

    def __post_init__(self) -> None:
        if self.minimum_trades < 1:
            raise ValueError("minimum_trades must be positive")
        if not math.isfinite(self.maximum_drawdown_percent) or not 0 < self.maximum_drawdown_percent <= 100:
            raise ValueError("maximum_drawdown_percent must be within 0..100")


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    strategy: str
    benchmark: bool
    return_percent: float
    net_pnl: float
    max_drawdown_percent: float
    total_fees: float
    total_slippage_cost: float
    total_funding_cost: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    trade_count: int
    exposure_time_percent: float
    beats_buy_and_hold: bool
    review_eligible: bool
    failed_gates: tuple[str, ...]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategySuiteReport:
    event_count: int
    symbol_count: int
    benchmark_return_percent: float
    rankings: tuple[StrategyComparison, ...]
    recommended_for_paper_review: str | None
    automatic_promotion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_strategy_suite(
    events: Iterable[MarketEvent],
    *,
    backtest_config: BacktestConfig | None = None,
    suite_config: StrategySuiteConfig | None = None,
) -> StrategySuiteReport:
    ordered_events = tuple(events)
    if not ordered_events:
        raise ValueError("strategy suite requires market events")
    config = suite_config or StrategySuiteConfig()
    backtester_config = backtest_config or BacktestConfig()

    factories = {
        "buy_and_hold": lambda: BuyAndHoldStrategy(),
        "trend": lambda: TrendFollowingStrategy(
            short_window=config.trend_short_window,
            long_window=config.trend_long_window,
            buffer_percent=config.trend_buffer_percent,
        ),
        "breakout": lambda: BreakoutStrategy(
            entry_window=config.breakout_entry_window,
            exit_window=config.breakout_exit_window,
            breakout_buffer_percent=config.breakout_buffer_percent,
        ),
        "mean_reversion": lambda: MeanReversionStrategy(
            window=config.mean_reversion_window,
            entry_zscore=config.mean_reversion_entry_zscore,
            exit_zscore=config.mean_reversion_exit_zscore,
        ),
    }
    results: dict[str, BacktestResult] = {}
    for name, factory in factories.items():
        results[name] = EventDrivenBacktester(backtester_config).run(
            ordered_events,
            factory(),
        )

    benchmark_return = results["buy_and_hold"].return_percent
    comparisons = [
        _comparison(
            name,
            result,
            benchmark_return=benchmark_return,
            config=config,
        )
        for name, result in results.items()
    ]
    rankings = tuple(
        sorted(
            comparisons,
            key=lambda item: (item.review_eligible, item.score, item.return_percent),
            reverse=True,
        )
    )
    recommended = next(
        (
            item.strategy
            for item in rankings
            if item.strategy != "buy_and_hold" and item.review_eligible
        ),
        None,
    )
    return StrategySuiteReport(
        event_count=len(ordered_events),
        symbol_count=len({event.symbol for event in ordered_events}),
        benchmark_return_percent=benchmark_return,
        rankings=rankings,
        recommended_for_paper_review=recommended,
        automatic_promotion=False,
    )


def _comparison(
    name: str,
    result: BacktestResult,
    *,
    benchmark_return: float,
    config: StrategySuiteConfig,
) -> StrategyComparison:
    failed: list[str] = []
    if result.trade_count < config.minimum_trades:
        failed.append("insufficient_trades")
    if result.max_drawdown_percent > config.maximum_drawdown_percent:
        failed.append("drawdown_limit_exceeded")
    if name != "buy_and_hold" and result.return_percent <= benchmark_return:
        failed.append("did_not_beat_buy_and_hold")
    if result.net_pnl <= 0:
        failed.append("non_positive_net_pnl")
    if result.total_fees < 0 or result.total_slippage_cost < 0 or result.total_funding_cost < 0:
        failed.append("invalid_cost_accounting")

    score = (
        result.return_percent
        - 0.75 * result.max_drawdown_percent
        + 0.25 * result.sharpe_ratio
        + 0.10 * result.sortino_ratio
    )
    return StrategyComparison(
        strategy=name,
        benchmark=name == "buy_and_hold",
        return_percent=result.return_percent,
        net_pnl=result.net_pnl,
        max_drawdown_percent=result.max_drawdown_percent,
        total_fees=result.total_fees,
        total_slippage_cost=result.total_slippage_cost,
        total_funding_cost=result.total_funding_cost,
        sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio,
        profit_factor=result.profit_factor,
        trade_count=result.trade_count,
        exposure_time_percent=result.exposure_time_percent,
        beats_buy_and_hold=name != "buy_and_hold" and result.return_percent > benchmark_return,
        review_eligible=name != "buy_and_hold" and not failed,
        failed_gates=tuple(failed),
        score=round(score, 8),
    )


__all__ = [
    "StrategyComparison",
    "StrategySuiteConfig",
    "StrategySuiteReport",
    "evaluate_strategy_suite",
]
