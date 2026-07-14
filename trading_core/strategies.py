"""Deterministic benchmark strategies for research baselines."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque

from .models import MarketEvent, PortfolioSnapshot, Side, Signal


class BuyAndHoldStrategy:
    """Buy the first observation for each symbol and hold until forced close."""

    def __init__(self, *, risk_percent: float = 1.0) -> None:
        self.risk_percent = risk_percent
        self._seen: set[str] = set()

    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None:
        if event.symbol in self._seen:
            return None
        self._seen.add(event.symbol)
        if event.symbol in portfolio.positions:
            return None
        return Signal(
            Side.BUY,
            requested_risk_percent=self.risk_percent,
            reason="benchmark_buy_and_hold",
        )


class TrendFollowingStrategy:
    """Long-only moving-average trend benchmark."""

    def __init__(
        self,
        *,
        short_window: int = 20,
        long_window: int = 50,
        buffer_percent: float = 0.0,
    ) -> None:
        if short_window <= 1 or long_window <= short_window:
            raise ValueError("trend windows require 1 < short < long")
        if not 0 <= buffer_percent <= 25:
            raise ValueError("buffer_percent must be within 0..25")
        self.short_window = short_window
        self.long_window = long_window
        self.buffer = buffer_percent / 100.0
        self._history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.long_window)
        )

    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None:
        history = self._history[event.symbol]
        history.append(event.mid)
        if len(history) < self.long_window:
            return None
        values = tuple(history)
        short_mean = statistics.fmean(values[-self.short_window:])
        long_mean = statistics.fmean(values)
        in_position = event.symbol in portfolio.positions
        if not in_position and short_mean > long_mean * (1.0 + self.buffer):
            return Signal(Side.BUY, reason="benchmark_trend_entry")
        if in_position and short_mean < long_mean * (1.0 - self.buffer):
            return Signal(Side.SELL, reason="benchmark_trend_exit")
        return None


class BreakoutStrategy:
    """Enter above the previous rolling high and exit below the rolling low."""

    def __init__(
        self,
        *,
        entry_window: int = 20,
        exit_window: int = 10,
        breakout_buffer_percent: float = 0.0,
    ) -> None:
        if entry_window <= 1 or exit_window <= 1:
            raise ValueError("breakout windows must exceed one event")
        if exit_window > entry_window:
            raise ValueError("exit_window cannot exceed entry_window")
        if not 0 <= breakout_buffer_percent <= 25:
            raise ValueError("breakout_buffer_percent must be within 0..25")
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.buffer = breakout_buffer_percent / 100.0
        self._history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.entry_window)
        )

    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None:
        history = self._history[event.symbol]
        prior = tuple(history)
        signal: Signal | None = None
        if len(prior) >= self.entry_window:
            in_position = event.symbol in portfolio.positions
            prior_high = max(prior)
            prior_low = min(prior[-self.exit_window:])
            if not in_position and event.mid > prior_high * (1.0 + self.buffer):
                signal = Signal(Side.BUY, reason="benchmark_breakout_entry")
            elif in_position and event.mid < prior_low:
                signal = Signal(Side.SELL, reason="benchmark_breakout_exit")
        history.append(event.mid)
        return signal


class MeanReversionStrategy:
    """Buy statistically depressed prices and exit near the rolling mean."""

    def __init__(
        self,
        *,
        window: int = 30,
        entry_zscore: float = 1.5,
        exit_zscore: float = 0.25,
    ) -> None:
        if window < 5:
            raise ValueError("mean-reversion window must be at least five")
        if not math.isfinite(entry_zscore) or entry_zscore <= 0:
            raise ValueError("entry_zscore must be positive")
        if not math.isfinite(exit_zscore) or not 0 <= exit_zscore < entry_zscore:
            raise ValueError("exit_zscore must be within 0..entry_zscore")
        self.window = window
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore
        self._history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )

    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None:
        history = self._history[event.symbol]
        prior = tuple(history)
        signal: Signal | None = None
        if len(prior) >= self.window:
            mean = statistics.fmean(prior)
            deviation = statistics.stdev(prior)
            zscore = (event.mid - mean) / deviation if deviation > 0 else 0.0
            in_position = event.symbol in portfolio.positions
            if not in_position and zscore <= -self.entry_zscore:
                signal = Signal(Side.BUY, reason="benchmark_mean_reversion_entry")
            elif in_position and zscore >= -self.exit_zscore:
                signal = Signal(Side.SELL, reason="benchmark_mean_reversion_exit")
        history.append(event.mid)
        return signal


__all__ = [
    "BreakoutStrategy",
    "BuyAndHoldStrategy",
    "MeanReversionStrategy",
    "TrendFollowingStrategy",
]
