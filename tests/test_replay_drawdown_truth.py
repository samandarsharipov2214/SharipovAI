"""Synthetic risk/accounting regressions; these fixtures are not market evidence."""
from dataclasses import replace

import pytest

from trading_core import (
    BacktestConfig, EventDrivenBacktester, MarketEvent, PurgedWalkForwardBacktester,
    PurgedWalkForwardConfig, Side, Signal, WalkForwardBacktester, WalkForwardConfig,
)


class BuyOnce:
    def __init__(self):
        self.entered = False

    def on_market(self, event, portfolio):
        if not self.entered:
            self.entered = True
            return Signal(Side.BUY)
        return None


def config():
    return BacktestConfig(
        initial_cash=100.0, minimum_notional=1.0,
        fee_rate=0.001, slippage_bps=2.0, market_impact_bps=0.0,
    )


def events(prices):
    return tuple(MarketEvent(index, "BTCUSDT", price, price)
                 for index, price in enumerate(prices, 1))


def test_liquidation_costs_are_in_drawdown_and_charged_only_once():
    result = EventDrivenBacktester(config()).run(events([100.0]), BuyOnce())
    assert len(result.fills) == 2
    assert result.fills[-1].synthetic_finalization
    assert result.net_pnl == pytest.approx(-result.total_fees - result.total_slippage_cost)
    assert result.max_drawdown_percent == pytest.approx(-result.return_percent)
    # Same timestamp has a pre-liquidation mark and an economically lower cash mark.
    assert result.equity_curve[0][0] == result.equity_curve[-1][0]
    assert result.equity_curve[-1][1] < result.equity_curve[0][1]


def test_open_inventory_has_no_fabricated_exit_cost():
    result = EventDrivenBacktester(replace(config(), force_close_at_end=False)).run(
        events([100.0]), BuyOnce(),
    )
    assert len(result.fills) == 1
    assert result.max_drawdown_percent == pytest.approx(-result.return_percent)
    assert result.net_pnl == pytest.approx(-result.total_fees - result.total_slippage_cost)


def test_recovery_does_not_erase_an_earlier_trough():
    result = EventDrivenBacktester(config()).run(events([100.0, 50.0, 150.0]), BuyOnce())
    assert result.net_pnl > 0
    # Risk is measured from the original 100 USDT through the earlier 50 quote.
    trough = result.equity_curve[1][1]
    assert result.max_drawdown_percent == pytest.approx(100.0 - trough)


@pytest.mark.parametrize("purged", [False, True])
@pytest.mark.parametrize("chain_capital", [False, True])
def test_walk_forward_keeps_cumulative_losses_across_windows(purged, chain_capital):
    kwargs = dict(train_events=2, test_events=3, step_events=3,
                  minimum_windows=2, chain_capital=chain_capital)
    if purged:
        runner = PurgedWalkForwardBacktester(config(), PurgedWalkForwardConfig(
            **kwargs, embargo_events=0,
        ))
    else:
        runner = WalkForwardBacktester(config(), WalkForwardConfig(**kwargs))
    result = runner.run(events([100, 100, 100, 100, 50, 100, 100, 50]),
                        lambda train, index: BuyOnce())
    assert len(result.windows) == 2
    # Both windows lose; their total drawdown exceeds either window's local loss.
    assert result.max_drawdown_percent == pytest.approx(-result.return_percent)
    assert result.max_drawdown_percent > max(w.result.max_drawdown_percent for w in result.windows)
    assert result.total_fees == pytest.approx(sum(w.result.total_fees for w in result.windows))
    assert result.ending_equity == pytest.approx(100 + sum(w.result.net_pnl for w in result.windows))
    assert result.metadata["drawdown_basis"] == (
        "chained_oos_equity" if chain_capital else "stitched_reset_window_pnl"
    )


@pytest.mark.parametrize("purged", [False, True])
def test_prior_window_peak_remains_the_reference_after_recovery(purged):
    kwargs = dict(train_events=2, test_events=3, step_events=3, minimum_windows=2)
    runner = (PurgedWalkForwardBacktester(config(), PurgedWalkForwardConfig(**kwargs, embargo_events=0))
              if purged else WalkForwardBacktester(config(), WalkForwardConfig(**kwargs)))
    result = runner.run(events([100, 100, 100, 150, 100, 100, 80, 120]),
                        lambda train, index: BuyOnce())
    first, second = result.windows
    peak = first.result.equity_curve[1][1]
    trough = second.result.equity_curve[1][1]
    assert result.net_pnl > 0
    assert peak > first.result.ending_equity
    assert result.max_drawdown_percent == pytest.approx((peak - trough) / peak * 100)


def test_no_trades_and_empty_input_have_zero_observed_drawdown():
    class Wait:
        def on_market(self, event, portfolio):
            return None

    for tape in [(), events([100, 50, 150])]:
        result = EventDrivenBacktester(config()).run(tape, Wait())
        assert result.max_drawdown_percent == 0
        assert result.ending_equity == 100
        assert not result.fills
