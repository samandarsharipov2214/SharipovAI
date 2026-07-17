"""Event-driven, no-lookahead backtesting and walk-forward evaluation."""
from __future__ import annotations

import math
import statistics
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from typing import Protocol

from capital_allocation import (
    CapitalAllocationPolicy,
    build_capital_allocation,
    correlation_group_for_symbol,
)

from .costs import ExecutionCostModel, validate_market_event
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


class Strategy(Protocol):
    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None: ...


class StrategyFactory(Protocol):
    def __call__(
        self,
        train_events: tuple[MarketEvent, ...],
        window_index: int,
    ) -> Strategy: ...


class EventDrivenBacktester:
    """Process immutable market events in order with deterministic costs."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self._validate_config()
        self.costs = ExecutionCostModel(
            fee_rate=self.config.fee_rate,
            maker_fee_rate=self.config.maker_fee_rate,
            slippage_bps=self.config.slippage_bps,
            market_impact_bps=self.config.market_impact_bps,
            max_participation_rate=self.config.max_participation_rate,
        )
        self.policy = CapitalAllocationPolicy(
            reserve_percent=self.config.reserve_percent,
            max_total_exposure_percent=self.config.max_total_exposure_percent,
            max_position_percent=self.config.max_position_percent,
            max_symbol_exposure_percent=self.config.max_position_percent,
            max_correlated_exposure_percent=self.config.max_correlated_exposure_percent,
            max_risk_per_trade_percent=self.config.max_risk_per_trade_percent,
            max_daily_loss_percent=100.0,
            minimum_notional=self.config.minimum_notional,
            leverage=1.0,
        )

    def run(
        self,
        events: Iterable[MarketEvent],
        strategy: Strategy,
    ) -> BacktestResult:
        started = time.perf_counter()
        cash = float(self.config.initial_cash)
        realized_pnl = 0.0
        gross_trading_pnl = 0.0
        total_fees = 0.0
        total_slippage = 0.0
        total_funding = 0.0
        positions: dict[str, Position] = {}
        last_funding_timestamp: dict[str, int] = {}
        fills: list[Fill] = []
        funding_payments: list[FundingPayment] = []
        closed_pnls: list[float] = []
        equity_curve: list[tuple[int, float]] = []
        last_events: dict[str, MarketEvent] = {}
        previous_timestamp = 0
        previous_event_key: tuple[int, str] = (0, "")
        peak_equity = cash
        max_drawdown = 0.0
        winning_closed = 0
        losing_closed = 0
        event_count = 0
        exposed_events = 0

        for event in events:
            validate_market_event(event)
            event_key = (event.timestamp_ms, event.symbol)
            if event_key <= previous_event_key:
                raise ValueError(
                    "market events must be strictly increasing by timestamp and symbol; "
                    "out-of-order or duplicate data creates lookahead ambiguity"
                )
            previous_event_key = event_key
            previous_timestamp = event.timestamp_ms
            event_count += 1
            last_events[event.symbol] = event

            if event.symbol in positions:
                (
                    cash,
                    total_funding,
                    positions[event.symbol],
                    funding_payment,
                ) = self._apply_funding(
                    event=event,
                    position=positions[event.symbol],
                    cash=cash,
                    total_funding=total_funding,
                    last_timestamp_ms=last_funding_timestamp.get(
                        event.symbol,
                        positions[event.symbol].opened_at_ms,
                    ),
                )
                last_funding_timestamp[event.symbol] = event.timestamp_ms
                if funding_payment is not None:
                    funding_payments.append(funding_payment)

            snapshot = self._snapshot(
                timestamp_ms=event.timestamp_ms,
                cash=cash,
                realized_pnl=realized_pnl,
                total_fees=total_fees,
                total_funding=total_funding,
                positions=positions,
                prices=last_events,
            )
            signal = strategy.on_market(event, snapshot)
            if signal is not None:
                if not isinstance(signal, Signal):
                    raise TypeError("strategy must return Signal or None")
                if signal.side is Side.BUY:
                    if event.symbol not in positions:
                        allocation = build_capital_allocation(
                            equity=snapshot.equity,
                            open_trades=[
                                {
                                    "status": "OPEN",
                                    "symbol": position.symbol,
                                    "notional": position.quantity
                                    * last_events.get(
                                        position.symbol,
                                        MarketEvent(
                                            event.timestamp_ms,
                                            position.symbol,
                                            position.entry_price,
                                            position.entry_price,
                                        ),
                                    ).mid,
                                    "correlation_group": position.correlation_group,
                                }
                                for position in positions.values()
                            ],
                            max_open_positions=self.config.max_open_positions,
                            stop_loss_percent=signal.stop_loss_percent,
                            fee_rate=self.config.fee_rate,
                            requested_risk_percent=signal.requested_risk_percent,
                            policy=self.policy,
                            symbol=event.symbol,
                            correlation_group=correlation_group_for_symbol(event.symbol),
                        )
                        if allocation["allowed"] and allocation["notional"] > 0:
                            quantity = allocation["notional"] / event.ask
                            cost = self.costs.estimate(
                                event,
                                side=Side.BUY,
                                quantity=quantity,
                                liquidity_role=signal.liquidity_role,
                            )
                            spent = cost.execution_price * quantity + cost.fee
                            if spent <= cash:
                                cash -= spent
                                total_fees += cost.fee
                                total_slippage += cost.slippage_cost
                                positions[event.symbol] = Position(
                                    symbol=event.symbol,
                                    quantity=quantity,
                                    entry_price=cost.execution_price,
                                    entry_notional=cost.execution_price * quantity,
                                    entry_fee=cost.fee,
                                    opened_at_ms=event.timestamp_ms,
                                    correlation_group=correlation_group_for_symbol(event.symbol),
                                )
                                last_funding_timestamp[event.symbol] = event.timestamp_ms
                                fills.append(
                                    Fill(
                                        timestamp_ms=event.timestamp_ms,
                                        symbol=event.symbol,
                                        side=Side.BUY,
                                        quantity=quantity,
                                        reference_price=cost.reference_price,
                                        execution_price=cost.execution_price,
                                        notional=cost.execution_price * quantity,
                                        fee=cost.fee,
                                        slippage_cost=cost.slippage_cost,
                                        realized_pnl=0.0,
                                        reason=signal.reason,
                                        liquidity_role=signal.liquidity_role,
                                        spread_cost=cost.spread_cost,
                                        participation_rate=cost.participation_rate,
                                    )
                                )
                elif signal.side is Side.SELL:
                    position = positions.pop(event.symbol, None)
                    last_funding_timestamp.pop(event.symbol, None)
                    if position is not None:
                        (
                            cash,
                            realized_pnl,
                            gross_trading_pnl,
                            total_fees,
                            total_slippage,
                            net,
                            fill,
                        ) = self._close_position(
                            event=event,
                            position=position,
                            signal=signal,
                            cash=cash,
                            realized_pnl=realized_pnl,
                            gross_trading_pnl=gross_trading_pnl,
                            total_fees=total_fees,
                            total_slippage=total_slippage,
                        )
                        closed_pnls.append(net)
                        winning_closed += int(net > 0)
                        losing_closed += int(net < 0)
                        fills.append(fill)
                else:
                    raise ValueError("unsupported strategy side")

            snapshot = self._snapshot(
                timestamp_ms=event.timestamp_ms,
                cash=cash,
                realized_pnl=realized_pnl,
                total_fees=total_fees,
                total_funding=total_funding,
                positions=positions,
                prices=last_events,
            )
            exposed_events += int(bool(positions))
            peak_equity = max(peak_equity, snapshot.equity)
            drawdown = (
                (peak_equity - snapshot.equity) / peak_equity * 100.0
                if peak_equity > 0
                else 0.0
            )
            max_drawdown = max(max_drawdown, drawdown)
            equity_curve.append((event.timestamp_ms, snapshot.equity))

        if self.config.force_close_at_end and positions:
            for symbol in sorted(tuple(positions)):
                event = last_events.get(symbol)
                if event is None:
                    raise RuntimeError(
                        f"cannot close {symbol}: final market event is unavailable"
                    )
                position = positions.pop(symbol)
                signal = Signal(
                    Side.SELL,
                    reason="forced_end_of_backtest",
                    liquidity_role="taker",
                )
                (
                    cash,
                    realized_pnl,
                    gross_trading_pnl,
                    total_fees,
                    total_slippage,
                    net,
                    fill,
                ) = self._close_position(
                    event=event,
                    position=position,
                    signal=signal,
                    cash=cash,
                    realized_pnl=realized_pnl,
                    gross_trading_pnl=gross_trading_pnl,
                    total_fees=total_fees,
                    total_slippage=total_slippage,
                )
                closed_pnls.append(net)
                winning_closed += int(net > 0)
                losing_closed += int(net < 0)
                fills.append(fill)
            if previous_timestamp:
                equity_curve.append((previous_timestamp, cash))

        ending_equity = cash + sum(
            position.quantity
            * last_events.get(
                position.symbol,
                MarketEvent(
                    previous_timestamp or 1,
                    position.symbol,
                    position.entry_price,
                    position.entry_price,
                ),
            ).bid
            for position in positions.values()
        )
        net_pnl = ending_equity - self.config.initial_cash
        sharpe, sortino = _risk_adjusted_ratios(equity_curve)
        profit_factor = _profit_factor(closed_pnls)
        result = BacktestResult(
            initial_cash=round(self.config.initial_cash, 8),
            ending_equity=round(ending_equity, 8),
            net_pnl=round(net_pnl, 8),
            return_percent=round(
                net_pnl / self.config.initial_cash * 100.0,
                8,
            ),
            max_drawdown_percent=round(max_drawdown, 8),
            total_fees=round(total_fees, 8),
            total_slippage_cost=round(total_slippage, 8),
            trade_count=len(fills),
            winning_closed_trades=winning_closed,
            losing_closed_trades=losing_closed,
            fills=tuple(fills),
            equity_curve=tuple(equity_curve),
            metadata={
                "event_driven": True,
                "lookahead_allowed": False,
                "bid_ask_mode": True,
                "fees_included": True,
                "slippage_included": True,
                "market_impact_included": True,
                "funding_included": True,
                "reserve_percent": self.config.reserve_percent,
                "minimum_notional": self.config.minimum_notional,
                "leverage": 1.0,
                "event_count": event_count,
                "closed_trade_count": len(closed_pnls),
                "duration_seconds": round(time.perf_counter() - started, 6),
            },
            total_funding_cost=round(total_funding, 8),
            gross_trading_pnl=round(gross_trading_pnl, 8),
            sharpe_ratio=round(sharpe, 8),
            sortino_ratio=round(sortino, 8),
            profit_factor=round(profit_factor, 8),
            exposure_time_percent=round(
                exposed_events / event_count * 100.0 if event_count else 0.0,
                8,
            ),
            funding_payments=tuple(funding_payments),
        )
        _record_backtest_metrics(result)
        return result

    def _apply_funding(
        self,
        *,
        event: MarketEvent,
        position: Position,
        cash: float,
        total_funding: float,
        last_timestamp_ms: int,
    ) -> tuple[float, float, Position, FundingPayment | None]:
        elapsed_ms = max(0, event.timestamp_ms - last_timestamp_ms)
        if elapsed_ms == 0 or event.funding_rate == 0:
            return cash, total_funding, position, None
        interval_ms = event.funding_interval_hours * 60.0 * 60.0 * 1_000.0
        fraction = elapsed_ms / interval_ms
        notional = position.quantity * event.mid
        amount = notional * event.funding_rate * fraction
        if not math.isfinite(amount):
            raise ValueError("funding calculation produced a non-finite amount")
        updated = replace(
            position,
            funding_paid=position.funding_paid + amount,
        )
        return (
            cash - amount,
            total_funding + amount,
            updated,
            FundingPayment(
                timestamp_ms=event.timestamp_ms,
                symbol=event.symbol,
                rate=event.funding_rate,
                notional=notional,
                interval_fraction=fraction,
                amount=amount,
            ),
        )

    def _close_position(
        self,
        *,
        event: MarketEvent,
        position: Position,
        signal: Signal,
        cash: float,
        realized_pnl: float,
        gross_trading_pnl: float,
        total_fees: float,
        total_slippage: float,
    ) -> tuple[float, float, float, float, float, float, Fill]:
        cost = self.costs.estimate(
            event,
            side=Side.SELL,
            quantity=position.quantity,
            liquidity_role=signal.liquidity_role,
        )
        proceeds = cost.execution_price * position.quantity
        gross = proceeds - position.entry_notional
        net = gross - position.entry_fee - cost.fee - position.funding_paid
        return (
            cash + proceeds - cost.fee,
            realized_pnl + net,
            gross_trading_pnl + gross,
            total_fees + cost.fee,
            total_slippage + cost.slippage_cost,
            net,
            Fill(
                timestamp_ms=event.timestamp_ms,
                symbol=event.symbol,
                side=Side.SELL,
                quantity=position.quantity,
                reference_price=cost.reference_price,
                execution_price=cost.execution_price,
                notional=proceeds,
                fee=cost.fee,
                slippage_cost=cost.slippage_cost,
                realized_pnl=net,
                reason=signal.reason,
                liquidity_role=signal.liquidity_role,
                spread_cost=cost.spread_cost,
                participation_rate=cost.participation_rate,
            ),
        )

    @staticmethod
    def _snapshot(
        *,
        timestamp_ms: int,
        cash: float,
        realized_pnl: float,
        total_fees: float,
        total_funding: float,
        positions: dict[str, Position],
        prices: dict[str, MarketEvent],
    ) -> PortfolioSnapshot:
        equity = cash
        for position in positions.values():
            market = prices.get(position.symbol)
            price = market.bid if market is not None else position.entry_price
            equity += position.quantity * price
        return PortfolioSnapshot(
            timestamp_ms=timestamp_ms,
            cash=round(cash, 12),
            equity=round(equity, 12),
            realized_pnl=round(realized_pnl, 12),
            total_fees=round(total_fees, 12),
            positions=dict(positions),
            total_funding_cost=round(total_funding, 12),
        )

    def _validate_config(self) -> None:
        values = {
            "initial_cash": self.config.initial_cash,
            "fee_rate": self.config.fee_rate,
            "maker_fee_rate": self.config.maker_fee_rate,
            "slippage_bps": self.config.slippage_bps,
            "market_impact_bps": self.config.market_impact_bps,
            "max_participation_rate": self.config.max_participation_rate,
            "reserve_percent": self.config.reserve_percent,
            "max_total_exposure_percent": self.config.max_total_exposure_percent,
            "max_position_percent": self.config.max_position_percent,
            "max_correlated_exposure_percent": self.config.max_correlated_exposure_percent,
            "max_risk_per_trade_percent": self.config.max_risk_per_trade_percent,
            "minimum_notional": self.config.minimum_notional,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"backtest config {name} must be finite")
        if self.config.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.config.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if self.config.minimum_notional <= 0:
            raise ValueError("minimum_notional must be positive")
        if not 0 <= self.config.fee_rate <= 0.05:
            raise ValueError("fee_rate must be within 0..0.05")
        if not 0 <= self.config.maker_fee_rate <= 0.05:
            raise ValueError("maker_fee_rate must be within 0..0.05")
        if not 0 <= self.config.slippage_bps <= 1_000:
            raise ValueError("slippage_bps must be within 0..1000")
        if not 0 <= self.config.market_impact_bps <= 10_000:
            raise ValueError("market_impact_bps must be within 0..10000")
        if not 0 < self.config.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be within 0..1")
        if not 0 <= self.config.reserve_percent < 100:
            raise ValueError("reserve_percent must be within 0..100")
        if not 0 < self.config.max_total_exposure_percent <= 100:
            raise ValueError("max_total_exposure_percent must be within 0..100")
        if (
            self.config.reserve_percent
            + self.config.max_total_exposure_percent
            > 100.000001
        ):
            raise ValueError("reserve plus total exposure exceeds 100 percent")


class WalkForwardBacktester:
    """Train only on past events and evaluate sequential out-of-sample windows."""

    def __init__(
        self,
        backtest_config: BacktestConfig | None = None,
        walk_forward_config: WalkForwardConfig | None = None,
    ) -> None:
        self.backtest_config = backtest_config or BacktestConfig()
        self.config = walk_forward_config or WalkForwardConfig()
        self._validate_config()

    def run(
        self,
        events: Sequence[MarketEvent] | Iterable[MarketEvent],
        strategy_factory: StrategyFactory
        | Callable[[tuple[MarketEvent, ...], int], Strategy],
    ) -> WalkForwardResult:
        ordered = tuple(events)
        if not ordered:
            raise ValueError("walk-forward requires market events")
        previous_key: tuple[int, str] = (0, "")
        for event in ordered:
            validate_market_event(event)
            event_key = (event.timestamp_ms, event.symbol)
            if event_key <= previous_key:
                raise ValueError(
                    "walk-forward events must be strictly increasing by timestamp and symbol"
                )
            previous_key = event_key

        windows: list[WalkForwardWindowResult] = []
        current_cash = self.backtest_config.initial_cash
        test_start = self.config.train_events
        window_index = 0

        while test_start + self.config.test_events <= len(ordered):
            train_start = 0 if self.config.anchored else max(
                0,
                test_start - self.config.train_events,
            )
            train = ordered[train_start:test_start]
            test = ordered[test_start:test_start + self.config.test_events]
            if len(train) < self.config.train_events:
                break

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
                "insufficient data for configured minimum walk-forward windows"
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
                "anchored": self.config.anchored,
                "chain_capital": self.config.chain_capital,
                "window_count": len(windows),
                "train_events": self.config.train_events,
                "test_events": self.config.test_events,
                "step_events": self.config.step_events,
            },
        )

    def _validate_config(self) -> None:
        for name in ("train_events", "test_events", "step_events", "minimum_windows"):
            value = getattr(self.config, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"walk-forward {name} must be a positive integer")
        if self.config.step_events > self.config.test_events:
            raise ValueError("walk-forward step_events cannot exceed test_events")


def _risk_adjusted_ratios(
    equity_curve: Sequence[tuple[int, float]],
) -> tuple[float, float]:
    if len(equity_curve) < 3:
        return 0.0, 0.0
    returns: list[float] = []
    for (_, previous), (_, current) in zip(equity_curve, equity_curve[1:]):
        if previous > 0:
            returns.append(current / previous - 1.0)
    if len(returns) < 2:
        return 0.0, 0.0
    mean_return = statistics.fmean(returns)
    deviation = statistics.stdev(returns)
    sharpe = mean_return / deviation * math.sqrt(len(returns)) if deviation > 0 else 0.0
    downside = [min(0.0, value) for value in returns]
    downside_variance = statistics.fmean(value * value for value in downside)
    downside_deviation = math.sqrt(downside_variance)
    sortino = (
        mean_return / downside_deviation * math.sqrt(len(returns))
        if downside_deviation > 0
        else 0.0
    )
    return sharpe, sortino


def _profit_factor(closed_pnls: Sequence[float]) -> float:
    gross_profit = sum(value for value in closed_pnls if value > 0)
    gross_loss = abs(sum(value for value in closed_pnls if value < 0))
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _record_backtest_metrics(result: BacktestResult) -> None:
    try:
        from observability.metrics import record_backtest_result

        record_backtest_result(result)
    except Exception:
        # Observability must never alter deterministic research output.
        return


__all__ = [
    "EventDrivenBacktester",
    "Strategy",
    "StrategyFactory",
    "WalkForwardBacktester",
]
