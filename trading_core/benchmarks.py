"""Mandatory benchmark comparison for strategy research."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .backtest import EventDrivenBacktester, Strategy
from .models import BacktestConfig, BacktestResult, MarketEvent
from .strategies import (
    BreakoutStrategy,
    BuyAndHoldStrategy,
    MeanReversionStrategy,
    TrendFollowingStrategy,
)


@dataclass(frozen=True, slots=True)
class BenchmarkEntry:
    name: str
    result: BacktestResult
    risk_adjusted_score: float


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteResult:
    entries: tuple[BenchmarkEntry, ...]
    ranking: tuple[str, ...]
    best_strategy: str
    metadata: dict[str, Any] = field(default_factory=dict)


def run_benchmark_suite(
    events: Iterable[MarketEvent],
    *,
    config: BacktestConfig | None = None,
) -> BenchmarkSuiteResult:
    """Run four fresh deterministic baselines on the same immutable event set."""

    event_set = tuple(events)
    if not event_set:
        raise ValueError("benchmark suite requires market events")
    factories: tuple[tuple[str, Callable[[], Strategy]], ...] = (
        ("buy_and_hold", BuyAndHoldStrategy),
        ("trend_following", TrendFollowingStrategy),
        ("breakout", BreakoutStrategy),
        ("mean_reversion", MeanReversionStrategy),
    )
    entries = tuple(
        _entry(
            name,
            EventDrivenBacktester(config).run(event_set, factory()),
        )
        for name, factory in factories
    )
    ranking = tuple(
        entry.name
        for entry in sorted(
            entries,
            key=lambda item: (
                item.risk_adjusted_score,
                item.result.net_pnl,
            ),
            reverse=True,
        )
    )
    return BenchmarkSuiteResult(
        entries=entries,
        ranking=ranking,
        best_strategy=ranking[0],
        metadata={
            "comparison_required": True,
            "benchmark_count": len(entries),
            "costs_included": True,
            "funding_included": True,
            "lookahead_allowed": False,
        },
    )


def compare_strategy_to_benchmarks(
    events: Iterable[MarketEvent],
    strategy_factory: Callable[[], Strategy],
    *,
    candidate_name: str = "candidate",
    config: BacktestConfig | None = None,
) -> BenchmarkSuiteResult:
    """Run a candidate and rank it against all mandatory baselines."""

    event_set = tuple(events)
    if not event_set:
        raise ValueError("strategy comparison requires market events")
    baseline = run_benchmark_suite(event_set, config=config)
    candidate = _entry(
        candidate_name,
        EventDrivenBacktester(config).run(event_set, strategy_factory()),
    )
    entries = (candidate, *baseline.entries)
    ranking = tuple(
        entry.name
        for entry in sorted(
            entries,
            key=lambda item: (
                item.risk_adjusted_score,
                item.result.net_pnl,
            ),
            reverse=True,
        )
    )
    return BenchmarkSuiteResult(
        entries=entries,
        ranking=ranking,
        best_strategy=ranking[0],
        metadata={
            **baseline.metadata,
            "candidate_name": candidate_name,
            "candidate_rank": ranking.index(candidate_name) + 1,
            "candidate_beats_buy_hold": ranking.index(candidate_name)
            < ranking.index("buy_and_hold"),
        },
    )


def _entry(name: str, result: BacktestResult) -> BenchmarkEntry:
    drawdown_penalty = max(1.0, result.max_drawdown_percent)
    score = (
        result.return_percent / drawdown_penalty
        + result.sharpe_ratio
        + 0.5 * result.sortino_ratio
    )
    return BenchmarkEntry(
        name=name,
        result=result,
        risk_adjusted_score=round(score, 8),
    )


__all__ = [
    "BenchmarkEntry",
    "BenchmarkSuiteResult",
    "compare_strategy_to_benchmarks",
    "run_benchmark_suite",
]
