"""Event-driven, no-lookahead backtesting foundation."""
from __future__ import annotations

import math
from collections.abc import Iterable
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
    MarketEvent,
    PortfolioSnapshot,
    Position,
    Side,
    Signal,
)


class Strategy(Protocol):
    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None: ...


class EventDrivenBacktester:
    """Process one immutable market event at a time in timestamp order."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self._validate_config()
        self.costs = ExecutionCostModel(
            fee_rate=self.config.fee_rate,
            slippage_bps=self.config.slippage_bps,
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
        cash = float(self.config.initial_cash)
        realized_pnl = 0.0
        total_fees = 0.0
        total_slippage = 0.0
        positions: dict[str, Position] = {}
        fills: list[Fill] = []
        equity_curve: list[tuple[int, float]] = []
        last_events: dict[str, MarketEvent] = {}
        previous_timestamp = 0
        peak_equity = cash
        max_drawdown = 0.0
        winning_closed = 0
        losing_closed = 0

        for event in events:
            validate_market_event(event)
            if event.timestamp_ms <= previous_timestamp:
                raise ValueError(
                    "market events must be strictly increasing; "
                    "out-of-order data would create lookahead ambiguity"
                )
            previous_timestamp = event.timestamp_ms
            last_events[event.symbol] = event
            snapshot = self._snapshot(
                timestamp_ms=event.timestamp_ms,
                cash=cash,
                realized_pnl=realized_pnl,
                total_fees=total_fees,
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
                                    )
                                )
                elif signal.side is Side.SELL:
                    position = positions.pop(event.symbol, None)
                    if position is not None:
                        cost = self.costs.estimate(
                            event,
                            side=Side.SELL,
                            quantity=position.quantity,
                        )
                        proceeds = cost.execution_price * position.quantity
                        net = (
                            proceeds
                            - position.entry_notional
                            - position.entry_fee
                            - cost.fee
                        )
                        cash += proceeds - cost.fee
                        realized_pnl += net
                        total_fees += cost.fee
                        total_slippage += cost.slippage_cost
                        winning_closed += int(net > 0)
                        losing_closed += int(net < 0)
                        fills.append(
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
                            )
                        )
                else:
                    raise ValueError("unsupported strategy side")

            snapshot = self._snapshot(
                timestamp_ms=event.timestamp_ms,
                cash=cash,
                realized_pnl=realized_pnl,
                total_fees=total_fees,
                positions=positions,
                prices=last_events,
            )
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
                cost = self.costs.estimate(
                    event,
                    side=Side.SELL,
                    quantity=position.quantity,
                )
                proceeds = cost.execution_price * position.quantity
                net = (
                    proceeds
                    - position.entry_notional
                    - position.entry_fee
                    - cost.fee
                )
                cash += proceeds - cost.fee
                realized_pnl += net
                total_fees += cost.fee
                total_slippage += cost.slippage_cost
                winning_closed += int(net > 0)
                losing_closed += int(net < 0)
                fills.append(
                    Fill(
                        timestamp_ms=event.timestamp_ms,
                        symbol=symbol,
                        side=Side.SELL,
                        quantity=position.quantity,
                        reference_price=cost.reference_price,
                        execution_price=cost.execution_price,
                        notional=proceeds,
                        fee=cost.fee,
                        slippage_cost=cost.slippage_cost,
                        realized_pnl=net,
                        reason="forced_end_of_backtest",
                    )
                )
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
        return BacktestResult(
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
                "reserve_percent": self.config.reserve_percent,
                "minimum_notional": self.config.minimum_notional,
                "leverage": 1.0,
            },
        )

    @staticmethod
    def _snapshot(
        *,
        timestamp_ms: int,
        cash: float,
        realized_pnl: float,
        total_fees: float,
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
        )

    def _validate_config(self) -> None:
        values = {
            "initial_cash": self.config.initial_cash,
            "fee_rate": self.config.fee_rate,
            "slippage_bps": self.config.slippage_bps,
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
        if not 0 <= self.config.slippage_bps <= 1_000:
            raise ValueError("slippage_bps must be within 0..1000")
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


__all__ = ["EventDrivenBacktester", "Strategy"]
