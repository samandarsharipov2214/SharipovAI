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
