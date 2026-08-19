"""Purged chronological walk-forward evaluation for research validation.

The evaluator keeps an explicit event-count embargo between every training slice
and its out-of-sample test slice. Embargo observations are never passed to the
strategy factory and are never evaluated as OOS trades in that window.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

from .backtest import EventDrivenBacktester, Strategy, StrategyFactory
from .costs import validate_market_event
from .models import (
    BacktestConfig,
    MarketEvent,
    WalkForwardResult,
    WalkForwardWindowResult,
)


@dataclass(frozen=True, slots=True)
class PurgedWalkForwardConfig:
    """Configuration for chronological OOS windows with an explicit embargo."""

    train_events: int = 500
    test_events: int = 100
    step_events: int = 100
    embargo_events: int = 0
    anchored: bool = False
    chain_capital: bool = True
    minimum_windows: int = 2

    def __post_init__(self) -> None:
        for name in ("train_events", "test_events", "step_events", "minimum_windows"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"purged walk-forward {name} must be a positive integer")
        if (
            isinstance(self.embargo_events, bool)
            or not isinstance(self.embargo_events, int)
            or self.embargo_events < 0
        ):
            raise ValueError("purged walk-forward embargo_events must be a non-negative integer")
        if self.step_events < self.test_events:
            raise ValueError(
                "purged walk-forward step_events must be >= test_events to prevent OOS overlap"
            )


class PurgedWalkForwardBacktester:
    """Evaluate strategies on disjoint chronological OOS windows after a purge gap."""

    def __init__(
        self,
        backtest_config: BacktestConfig | None = None,
        walk_forward_config: PurgedWalkForwardConfig | None = None,
    ) -> None:
        self.backtest_config = backtest_config or BacktestConfig()
        self.config = walk_forward_config or PurgedWalkForwardConfig()

    def run(
        self,
        events: Sequence[MarketEvent] | Iterable[MarketEvent],
        strategy_factory: StrategyFactory
        | Callable[[tuple[MarketEvent, ...], int], Strategy],
    ) -> WalkForwardResult:
        ordered = tuple(events)
        if not ordered:
            raise ValueError("purged walk-forward requires market events")

        previous_key: tuple[int, str] = (0, "")
        for event in ordered:
            validate_market_event(event)
            event_key = (event.timestamp_ms, event.symbol)
            if event_key <= previous_key:
                raise ValueError(
                    "purged walk-forward events must be strictly increasing by timestamp and symbol"
                )
            previous_key = event_key

        windows: list[WalkForwardWindowResult] = []
        current_cash = self.backtest_config.initial_cash
        test_start = self.config.train_events + self.config.embargo_events
        window_index = 0

        while test_start + self.config.test_events <= len(ordered):
            train_end = test_start - self.config.embargo_events
            train_start = 0 if self.config.anchored else train_end - self.config.train_events
            if train_start < 0:
                break

            train = ordered[train_start:train_end]
            test = ordered[test_start:test_start + self.config.test_events]
            if len(train) < self.config.train_events or len(test) != self.config.test_events:
                break
            if train[-1].timestamp_ms >= test[0].timestamp_ms:
                raise ValueError("purged walk-forward training must end before OOS evaluation")

            strategy = strategy_factory(tuple(train), window_index)
            initial_cash = (
                current_cash
                if self.config.chain_capital
                else self.backtest_config.initial_cash
            )
            config = replace(
                self.backtest_config,
                initial_cash=initial_cash,
                force_close_at_end=True,
            )
            result = EventDrivenBacktester(config).run(test, strategy)
            windows.append(
                WalkForwardWindowResult(
                    window_index=window_index,
                    train_start_ms=train[0].timestamp_ms,
                    train_end_ms=train[-1].timestamp_ms,
                    test_start_ms=test[0].timestamp_ms,
                    test_end_ms=test[-1].timestamp_ms,
                    train_event_count=len(train),
                    test_event_count=len(test),
                    result=result,
                )
            )
            if self.config.chain_capital:
                current_cash = result.ending_equity
            test_start += self.config.step_events
            window_index += 1

        if len(windows) < self.config.minimum_windows:
            raise ValueError(
                "insufficient data for configured minimum purged walk-forward windows"
            )

        ending_equity = (
            windows[-1].result.ending_equity
            if self.config.chain_capital
            else self.backtest_config.initial_cash
            + sum(window.result.net_pnl for window in windows)
        )
        net_pnl = ending_equity - self.backtest_config.initial_cash
        profitable = sum(window.result.net_pnl > 0 for window in windows)
        return WalkForwardResult(
            windows=tuple(windows),
            initial_cash=self.backtest_config.initial_cash,
            ending_equity=round(ending_equity, 8),
            net_pnl=round(net_pnl, 8),
            return_percent=round(
                net_pnl / self.backtest_config.initial_cash * 100.0,
                8,
            ),
            profitable_windows=profitable,
            profitable_window_percent=round(
                profitable / len(windows) * 100.0,
                8,
            ),
            max_drawdown_percent=max(
                window.result.max_drawdown_percent for window in windows
            ),
            total_fees=round(
                sum(window.result.total_fees for window in windows),
                8,
            ),
            total_slippage_cost=round(
                sum(window.result.total_slippage_cost for window in windows),
                8,
            ),
            total_funding_cost=round(
                sum(window.result.total_funding_cost for window in windows),
                8,
            ),
            metadata={
                "lookahead_allowed": False,
                "out_of_sample_only": True,
                "purged_walk_forward": True,
                "embargo_unit": "events",
                "embargo_events": self.config.embargo_events,
                "anchored": self.config.anchored,
                "chain_capital": self.config.chain_capital,
                "window_count": len(windows),
                "train_events": self.config.train_events,
                "test_events": self.config.test_events,
                "step_events": self.config.step_events,
                "oos_overlap_allowed": False,
            },
        )


__all__ = ["PurgedWalkForwardBacktester", "PurgedWalkForwardConfig"]
