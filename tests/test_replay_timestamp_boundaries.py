"""Synthetic chronology regressions, not evidence of strategy profitability."""
from dataclasses import asdict, replace

import pytest

from trading_core import (
    BacktestConfig, MarketEvent, PurgedWalkForwardBacktester,
    PurgedWalkForwardConfig, Side, Signal, WalkForwardBacktester, WalkForwardConfig,
)


class RecordWait:
    def __init__(self, seen):
        self.seen = seen

    def on_market(self, event, portfolio):
        self.seen.append(event)
        return None


def tape(groups=20):
    # Missing symbols and unequal timestamp batches reproduce actual panel shape.
    return tuple(MarketEvent(at, symbol, 100 + at, 100.1 + at)
                 for at in range(1, groups + 1)
                 for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")[:2 + at % 2])


def run(events, *, purged, anchored=False, embargo=0, train=3, test=3, step=3):
    captured = []

    def factory(training, index):
        observed = []
        captured.append((training, observed))
        return RecordWait(observed)

    kwargs = dict(train_events=train, test_events=test, step_events=step,
                  minimum_windows=2, anchored=anchored)
    config = BacktestConfig(initial_cash=100.0)
    runner = (PurgedWalkForwardBacktester(config, PurgedWalkForwardConfig(
        **kwargs, embargo_events=embargo)) if purged else
        WalkForwardBacktester(config, WalkForwardConfig(**kwargs)))
    return runner.run(events, factory), captured


@pytest.mark.parametrize("purged,embargo", [(False, 0), (True, 0), (True, 1), (True, 3)])
@pytest.mark.parametrize("anchored", [False, True])
def test_whole_timestamp_batches_keep_training_past_and_oos_disjoint(purged, embargo, anchored):
    events = tape()
    result, captured = run(events, purged=purged, embargo=embargo, anchored=anchored)
    seen_oos = set()
    previous_end = 0
    for window, (train, test) in zip(result.windows, captured, strict=True):
        assert train[-1].timestamp_ms < test[0].timestamp_ms
        assert test[0].timestamp_ms > previous_end
        assert len(train) >= 3 and len(test) >= 3
        assert window.train_event_count == len(train)
        assert window.test_event_count == len(test)
        for selection in (train, test):
            # A boundary must never select just one symbol from a simultaneous batch.
            times = {e.timestamp_ms for e in selection}
            assert tuple(selection) == tuple(e for e in events if e.timestamp_ms in times)
        gap = [e for e in events if train[-1].timestamp_ms < e.timestamp_ms < test[0].timestamp_ms]
        assert len(gap) >= embargo
        test_times = {e.timestamp_ms for e in test}
        assert seen_oos.isdisjoint(test_times)
        seen_oos.update(test_times)
        previous_end = test[-1].timestamp_ms
    assert result.ending_equity == 100.0
    assert result.total_fees == result.net_pnl == result.max_drawdown_percent == 0
    assert result.metadata["window_boundary_unit"] == "complete_timestamp_batches"
    assert result.metadata["event_count_contract"] == "minimum_rows_rounded_to_timestamp_boundaries"


@pytest.mark.parametrize("purged", [False, True])
def test_nonoverlapping_steps_can_leave_an_explicit_gap(purged):
    events = tuple(MarketEvent(at, "BTCUSDT", 100, 100) for at in range(1, 12))
    result, _ = run(events, purged=purged, train=3, test=2, step=4)
    assert [(w.train_end_ms, w.test_start_ms, w.test_end_ms) for w in result.windows] == [
        (3, 4, 5), (7, 8, 9),
    ]


@pytest.mark.parametrize("purged", [False, True])
def test_entire_single_timestamp_cannot_be_both_train_and_test(purged):
    events = tuple(MarketEvent(1, f"ASSET{i:02}USDT", 100, 100) for i in range(12))
    with pytest.raises(ValueError, match="insufficient data"):
        run(events, purged=purged)


@pytest.mark.parametrize("purged", [False, True])
def test_future_prices_do_not_change_already_completed_windows(purged):
    events = tape()
    original, captured = run(events, purged=purged)
    cutoff = original.windows[1].test_end_ms
    altered = tuple(replace(e, bid=10000, ask=10001) if e.timestamp_ms > cutoff else e
                    for e in events)
    changed, changed_captured = run(altered, purged=purged)
    def economic_windows(result):
        windows = [asdict(w) for w in result.windows[:2]]
        for window in windows:
            window["result"]["metadata"].pop("duration_seconds")
        return windows

    assert economic_windows(changed) == economic_windows(original)
    assert changed_captured[:2] == captured[:2]


@pytest.mark.parametrize("purged", [False, True])
@pytest.mark.parametrize("chain_capital", [False, True])
def test_grouped_portfolio_costs_and_capital_remain_chronological(purged, chain_capital):
    class BuyEach:
        def on_market(self, event, portfolio):
            if event.symbol not in portfolio.positions:
                return Signal(Side.BUY)

    events = tuple(replace(e, bid=100.0, ask=100.0) for e in tape(10))
    config = BacktestConfig(initial_cash=100.0, minimum_notional=1.0,
                            fee_rate=0.001, slippage_bps=2.0, market_impact_bps=0.0)
    options = dict(train_events=3, test_events=3, step_events=3,
                   minimum_windows=2, chain_capital=chain_capital)
    runner = (PurgedWalkForwardBacktester(config, PurgedWalkForwardConfig(**options))
              if purged else WalkForwardBacktester(config, WalkForwardConfig(**options)))
    result = runner.run(events, lambda train, index: BuyEach())
    assert result.net_pnl == pytest.approx(-result.total_fees - result.total_slippage_cost)
    assert result.ending_equity == pytest.approx(100 + sum(w.result.net_pnl for w in result.windows))
    assert result.max_drawdown_percent == pytest.approx(-result.return_percent)
    for previous, current in zip(result.windows, result.windows[1:]):
        assert max(f.timestamp_ms for f in previous.result.fills) < min(
            f.timestamp_ms for f in current.result.fills)
        assert current.result.initial_cash == (previous.result.ending_equity if chain_capital else 100)
