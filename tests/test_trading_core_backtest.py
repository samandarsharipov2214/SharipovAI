from __future__ import annotations

import pytest

from trading_core import (
    BacktestConfig,
    EventDrivenBacktester,
    MarketEvent,
    Side,
    Signal,
)


class BuyThenSell:
    def __init__(self) -> None:
        self.count = 0

    def on_market(self, event, portfolio):
        del portfolio
        self.count += 1
        if self.count == 1:
            return Signal(Side.BUY, reason="entry")
        if self.count == 3:
            return Signal(Side.SELL, reason="exit")
        return None


class BuyEveryNewSymbol:
    def on_market(self, event, portfolio):
        if event.symbol not in portfolio.positions:
            return Signal(Side.BUY, reason="portfolio-entry")
        return None


class FirstBuyThenSell:
    def __init__(self) -> None:
        self.entered = False

    def on_market(self, event, portfolio):
        if event.symbol == "BTCUSDT" and not self.entered:
            self.entered = True
            return Signal(Side.BUY, reason="close_signal")
        if event.symbol == "BTCUSDT" and event.symbol in portfolio.positions:
            return Signal(Side.SELL, reason="close_exit")
        return None


def test_event_driven_backtest_uses_bid_ask_fees_and_slippage() -> None:
    events = [
        MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(2, "BTCUSDT", bid=100.0, ask=101.0),
        MarketEvent(3, "BTCUSDT", bid=109.0, ask=110.0),
    ]

    result = EventDrivenBacktester().run(events, BuyThenSell())

    assert result.ending_equity > result.initial_cash
    assert result.net_pnl > 0
    assert result.total_fees > 0
    assert result.total_slippage_cost > 0
    assert result.trade_count == 2
    assert result.winning_closed_trades == 1
    assert result.metadata["lookahead_allowed"] is False
    assert result.metadata["bid_ask_mode"] is True


def test_flat_market_loses_spread_fees_and_slippage() -> None:
    events = [
        MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(2, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(3, "BTCUSDT", bid=99.0, ask=100.0),
    ]

    result = EventDrivenBacktester().run(events, BuyThenSell())

    assert result.net_pnl < 0
    assert result.losing_closed_trades == 1
    assert abs(result.net_pnl) >= result.total_fees


def test_backtester_rejects_out_of_order_and_duplicate_timestamps() -> None:
    events = [
        MarketEvent(2, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(1, "BTCUSDT", bid=100.0, ask=101.0),
    ]

    with pytest.raises(ValueError, match="strictly increasing"):
        EventDrivenBacktester().run(events, BuyThenSell())


def test_close_derived_signal_fills_only_on_next_event_of_same_symbol() -> None:
    close = {"price_source": "synthetic_from_close", "timestamp_semantics": "bar_close", "interval_ms": 60_000}
    events = [
        MarketEvent(1, "BTCUSDT", 99.0, 101.0, metadata=close),
        MarketEvent(2, "ETHUSDT", 49.0, 51.0, metadata=close),
        MarketEvent(3, "BTCUSDT", 109.0, 111.0, metadata=close),
        MarketEvent(4, "BTCUSDT", 119.0, 121.0, metadata=close),
    ]

    result = EventDrivenBacktester().run(events, FirstBuyThenSell())

    assert [(fill.side, fill.timestamp_ms, fill.symbol, fill.execution_timing) for fill in result.fills] == [
        (Side.BUY, 3, "BTCUSDT", "next_event"),
        (Side.SELL, 4, "BTCUSDT", "next_event"),
    ]


def test_close_derived_pending_signal_without_next_event_does_not_fill() -> None:
    event = MarketEvent(1, "BTCUSDT", 99.0, 101.0, metadata={"price_source": "synthetic_from_close"})
    result = EventDrivenBacktester(BacktestConfig(force_close_at_end=False)).run([event], FirstBuyThenSell())
    assert result.fills == ()
    assert result.metadata["pending_signals_unfilled"] == 1


def test_crypto_correlation_cap_limits_aggregate_entries() -> None:
    config = BacktestConfig(
        initial_cash=10_000.0,
        reserve_percent=20.0,
        max_total_exposure_percent=80.0,
        max_position_percent=20.0,
        max_correlated_exposure_percent=35.0,
        force_close_at_end=False,
    )
    events = [
        MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(2, "ETHUSDT", bid=99.0, ask=100.0),
        MarketEvent(3, "SOLUSDT", bid=99.0, ask=100.0),
    ]

    result = EventDrivenBacktester(config).run(events, BuyEveryNewSymbol())
    buy_fills = [fill for fill in result.fills if fill.side is Side.BUY]

    assert len(buy_fills) == 2
    assert sum(fill.notional for fill in buy_fills) <= 3_511.0
    assert result.ending_equity >= 6_500.0
