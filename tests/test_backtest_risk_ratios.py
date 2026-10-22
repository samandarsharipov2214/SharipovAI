import math
import statistics

import pytest

from trading_core import BacktestConfig, BuyAndHoldStrategy, EventDrivenBacktester, MarketEvent
from trading_core.backtest import _risk_adjusted_ratios


def reference_ratios(equities):
    returns = [b / a - 1 for a, b in zip(equities, equities[1:])]
    mean = statistics.fmean(returns)
    deviation = statistics.stdev(returns)
    downside = math.sqrt(statistics.fmean(min(0, r) ** 2 for r in returns))
    return (mean / deviation * math.sqrt(len(returns)),
            mean / downside * math.sqrt(len(returns)))


def test_entry_costs_cannot_disappear_from_risk_adjusted_result():
    result = EventDrivenBacktester(BacktestConfig(
        fee_rate=.01, slippage_bps=0, market_impact_bps=0,
        force_close_at_end=False,
    )).run([MarketEvent(i, 'BTCUSDT', p, p)
            for i, p in enumerate([100, 100.1, 100.3, 100.6], 1)], BuyAndHoldStrategy())
    assert result.net_pnl == -8
    expected = reference_ratios([result.initial_cash, *(v for _, v in result.equity_curve)])
    assert result.sharpe_ratio == pytest.approx(expected[0], abs=1e-8)
    assert result.sortino_ratio == pytest.approx(expected[1], abs=1e-8)
    assert result.sharpe_ratio < 0
    assert result.sortino_ratio < 0


def test_same_timestamp_partial_valuations_are_not_extra_periods():
    # Includes the final-liquidation value, which supersedes its mark at t=3.
    complete = [(1, 98.), (2, 101.), (3, 99.)]
    partial = [(1, 99.), (1, 98.), (2, 97.), (2, 101.), (3, 102.), (3, 99.)]
    expected = reference_ratios([100., 98., 101., 99.])
    assert _risk_adjusted_ratios(complete, initial_equity=100.) == pytest.approx(expected)
    assert _risk_adjusted_ratios(partial, initial_equity=100.) == pytest.approx(expected)


@pytest.mark.parametrize('curve', [[], [(1, 98.)], [(1, 99.), (1, 98.)]])
def test_fewer_than_two_observation_returns_have_no_risk_ratio(curve):
    assert _risk_adjusted_ratios(curve, initial_equity=100.) == (0., 0.)


def test_constant_equity_has_zero_ratios():
    assert _risk_adjusted_ratios([(1, 100.), (2, 100.)], initial_equity=100.) == (0., 0.)
