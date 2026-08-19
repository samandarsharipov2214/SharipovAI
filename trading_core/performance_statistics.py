"""Advisory robustness statistics for PAPER/replay evaluation.

This module derives bounded, reproducible statistics from an immutable
``BacktestResult``.  It does not grant execution authority or change strategy
parameters.  Confidence intervals are bootstrap estimates over realized closed
trade PnL and use a Bonferroni-style family-wise adjustment when multiple
candidate variants were tested.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Sequence

from .models import BacktestResult, Side


@dataclass(frozen=True, slots=True)
class PerformanceStatistics:
    closed_trade_count: int
    expectancy: float
    profit_factor: float
    max_drawdown_percent: float
    turnover_ratio: float
    turnover_percent: float
    bootstrap_mean_lower: float
    bootstrap_mean_upper: float
    confidence_level: float
    familywise_confidence_level: float
    tested_variants: int
    positive_expectancy_supported: bool
    sufficient_evidence: bool
    execution_authority: bool = False


def summarize_performance(
    result: BacktestResult,
    *,
    bootstrap_samples: int = 2_000,
    confidence_level: float = 0.95,
    tested_variants: int = 1,
    seed: int = 0,
) -> PerformanceStatistics:
    """Return deterministic advisory robustness statistics for one result.

    ``tested_variants`` is the number of strategy/parameter candidates examined
    in the same selection family.  The reported bootstrap interval uses
    ``alpha / tested_variants`` so a positive lower bound is not obtained by
    silently ignoring multiple testing.
    """

    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    if tested_variants <= 0:
        raise ValueError("tested_variants must be positive")
    if result.initial_cash <= 0:
        raise ValueError("result.initial_cash must be positive")

    closed_pnls = tuple(
        float(fill.realized_pnl)
        for fill in result.fills
        if fill.side is Side.SELL and not fill.synthetic_finalization
    )
    expectancy = _mean(closed_pnls)
    turnover_ratio = sum(abs(float(fill.notional)) for fill in result.fills) / float(
        result.initial_cash
    )

    alpha = 1.0 - confidence_level
    adjusted_alpha = alpha / tested_variants
    familywise_confidence = 1.0 - adjusted_alpha
    lower, upper = _bootstrap_mean_interval(
        closed_pnls,
        samples=bootstrap_samples,
        alpha=adjusted_alpha,
        seed=seed,
    )
    sufficient = bool(closed_pnls)

    return PerformanceStatistics(
        closed_trade_count=len(closed_pnls),
        expectancy=round(expectancy, 8),
        profit_factor=round(float(result.profit_factor), 8),
        max_drawdown_percent=round(float(result.max_drawdown_percent), 8),
        turnover_ratio=round(turnover_ratio, 8),
        turnover_percent=round(turnover_ratio * 100.0, 8),
        bootstrap_mean_lower=round(lower, 8),
        bootstrap_mean_upper=round(upper, 8),
        confidence_level=round(confidence_level, 8),
        familywise_confidence_level=round(familywise_confidence, 8),
        tested_variants=tested_variants,
        positive_expectancy_supported=bool(sufficient and lower > 0.0),
        sufficient_evidence=sufficient,
    )


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    value = sum(values) / len(values)
    if not math.isfinite(value):
        raise ValueError("closed trade PnL produced a non-finite expectancy")
    return value


def _bootstrap_mean_interval(
    values: Sequence[float],
    *,
    samples: int,
    alpha: float,
    seed: int,
) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        value = float(values[0])
        return value, value

    rng = random.Random(seed)
    count = len(values)
    means = sorted(
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(samples)
    )
    lower_index = max(0, min(samples - 1, math.floor((alpha / 2.0) * samples)))
    upper_index = max(
        0,
        min(samples - 1, math.ceil((1.0 - alpha / 2.0) * samples) - 1),
    )
    return float(means[lower_index]), float(means[upper_index])


__all__ = ["PerformanceStatistics", "summarize_performance"]
