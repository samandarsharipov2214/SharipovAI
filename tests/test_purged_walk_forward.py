from __future__ import annotations

import pytest

from trading_core import (
    BacktestConfig,
    BuyAndHoldStrategy,
    MarketEvent,
    PurgedWalkForwardBacktester,
    PurgedWalkForwardConfig,
)


def _events(count: int = 80) -> tuple[MarketEvent, ...]:
    return tuple(
        MarketEvent(
            timestamp_ms=index,
            symbol="BTCUSDT",
            bid=100.0 + index,
            ask=100.1 + index,
            volume=1_000_000.0,
        )
        for index in range(1, count + 1)
    )


def _backtest_config() -> BacktestConfig:
    return BacktestConfig(
        fee_rate=0.0,
        maker_fee_rate=0.0,
        slippage_bps=0.0,
        market_impact_bps=0.0,
    )


def test_purged_config_rejects_overlap_and_invalid_embargo() -> None:
    with pytest.raises(ValueError, match="step_events must be >= test_events"):
        PurgedWalkForwardConfig(
            train_events=20,
            test_events=10,
            step_events=9,
        )

    with pytest.raises(ValueError, match="embargo_events must be a non-negative integer"):
        PurgedWalkForwardConfig(
            train_events=20,
            test_events=10,
            step_events=10,
            embargo_events=-1,
        )


def test_embargo_events_are_excluded_from_training_and_oos_window() -> None:
    captured_train_timestamps: list[tuple[int, ...]] = []

    def factory(train, window_index):
        del window_index
        captured_train_timestamps.append(tuple(event.timestamp_ms for event in train))
        return BuyAndHoldStrategy()

    runner = PurgedWalkForwardBacktester(
        _backtest_config(),
        PurgedWalkForwardConfig(
            train_events=20,
            test_events=10,
            step_events=10,
            embargo_events=5,
            minimum_windows=2,
        ),
    )

    result = runner.run(_events(), factory)

    assert captured_train_timestamps[0] == tuple(range(1, 21))
    assert result.windows[0].test_start_ms == 26
    assert set(range(21, 26)).isdisjoint(captured_train_timestamps[0])

    assert captured_train_timestamps[1] == tuple(range(11, 31))
    assert result.windows[1].test_start_ms == 36
    assert set(range(31, 36)).isdisjoint(captured_train_timestamps[1])

    assert result.metadata["lookahead_allowed"] is False
    assert result.metadata["out_of_sample_only"] is True
    assert result.metadata["purged_walk_forward"] is True
    assert result.metadata["embargo_unit"] == "events"
    assert result.metadata["embargo_events"] == 5
    assert result.metadata["oos_overlap_allowed"] is False


def test_step_larger_than_test_creates_disjoint_oos_windows() -> None:
    runner = PurgedWalkForwardBacktester(
        _backtest_config(),
        PurgedWalkForwardConfig(
            train_events=20,
            test_events=10,
            step_events=15,
            embargo_events=2,
            minimum_windows=2,
        ),
    )

    result = runner.run(_events(), lambda train, index: BuyAndHoldStrategy())

    assert len(result.windows) >= 2
    assert result.windows[0].train_end_ms == 20
    assert result.windows[0].test_start_ms == 23
    assert result.windows[0].test_end_ms == 32
    assert result.windows[1].test_start_ms == 38
    assert result.windows[0].test_end_ms < result.windows[1].test_start_ms
    assert result.metadata["step_events"] == 15
    assert result.metadata["test_events"] == 10
