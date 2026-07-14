from __future__ import annotations

import pytest

from trading_core import (
    BacktestConfig,
    BuyAndHoldStrategy,
    EventDrivenBacktester,
    MarketEvent,
    Side,
    Signal,
    WalkForwardBacktester,
    WalkForwardConfig,
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


def _event(index: int, price: float, *, funding: float = 0.0) -> MarketEvent:
    return MarketEvent(
        timestamp_ms=index * 8 * 60 * 60 * 1_000,
        symbol="BTCUSDT",
        bid=price,
        ask=price,
        volume=1_000_000.0,
        funding_rate=funding,
        funding_interval_hours=8.0,
    )


def test_backtester_charges_positive_long_funding() -> None:
    events = [
        _event(1, 100.0, funding=0.001),
        _event(2, 100.0, funding=0.001),
        _event(3, 100.0, funding=0.001),
    ]
    config = BacktestConfig(
        fee_rate=0.0,
        maker_fee_rate=0.0,
        slippage_bps=0.0,
        market_impact_bps=0.0,
    )

    result = EventDrivenBacktester(config).run(events, BuyThenSell())

    assert result.total_funding_cost > 0
    assert len(result.funding_payments) == 2
    assert result.net_pnl == pytest.approx(-result.total_funding_cost)
    assert result.metadata["funding_included"] is True


def test_market_impact_increases_slippage_with_participation() -> None:
    event = MarketEvent(
        timestamp_ms=1,
        symbol="BTCUSDT",
        bid=99.0,
        ask=100.0,
        volume=100.0,
    )
    config = BacktestConfig(
        fee_rate=0.0,
        maker_fee_rate=0.0,
        slippage_bps=1.0,
        market_impact_bps=100.0,
        max_participation_rate=0.20,
    )
    model = EventDrivenBacktester(config).costs

    small = model.estimate(event, side=Side.BUY, quantity=1.0)
    large = model.estimate(event, side=Side.BUY, quantity=10.0)

    assert large.effective_slippage_bps > small.effective_slippage_bps
    assert large.participation_rate == pytest.approx(0.10)


def test_walk_forward_uses_sequential_out_of_sample_windows() -> None:
    events = tuple(
        MarketEvent(
            timestamp_ms=index,
            symbol="BTCUSDT",
            bid=100.0 + index,
            ask=100.1 + index,
            volume=1_000_000.0,
        )
        for index in range(1, 81)
    )
    runner = WalkForwardBacktester(
        BacktestConfig(
            fee_rate=0.0,
            maker_fee_rate=0.0,
            slippage_bps=0.0,
            market_impact_bps=0.0,
        ),
        WalkForwardConfig(
            train_events=30,
            test_events=20,
            step_events=20,
            minimum_windows=2,
        ),
    )

    result = runner.run(events, lambda train, index: BuyAndHoldStrategy())

    assert len(result.windows) == 2
    assert result.windows[0].train_end_ms < result.windows[0].test_start_ms
    assert result.windows[1].train_end_ms < result.windows[1].test_start_ms
    assert result.metadata["out_of_sample_only"] is True
    assert result.metadata["lookahead_allowed"] is False
