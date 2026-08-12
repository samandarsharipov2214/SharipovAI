"""Contracts for the first explicitly non-benchmark Alpha candidate."""
from __future__ import annotations

import pytest

from trading_core.alpha_strategies import (
    RegimeFilteredBreakoutConfig,
    RegimeFilteredBreakoutStrategy,
)
from trading_core.models import MarketEvent, PortfolioSnapshot, Position, Side


def _event(
    timestamp_ms: int,
    price: float,
    *,
    volume: float = 100.0,
    metadata: dict[str, object] | None = None,
) -> MarketEvent:
    canonical_metadata: dict[str, object] = {
        "market_type": "spot",
        "price_source": "synthetic_from_close",
        "interval_ms": 60_000,
        "timestamp_semantics": "bar_close",
    }
    if metadata:
        canonical_metadata.update(metadata)
    return MarketEvent(
        timestamp_ms=timestamp_ms,
        symbol="BTCUSDT",
        bid=price - 0.01,
        ask=price + 0.01,
        volume=volume,
        metadata=canonical_metadata,
    )


def _flat(timestamp_ms: int) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp_ms=timestamp_ms,
        cash=10_000.0,
        equity=10_000.0,
        realized_pnl=0.0,
        total_fees=0.0,
        positions={},
    )


def _long(timestamp_ms: int, *, entry_price: float = 100.0) -> PortfolioSnapshot:
    position = Position(
        symbol="BTCUSDT",
        quantity=1.0,
        entry_price=entry_price,
        entry_notional=entry_price,
        entry_fee=0.1,
        opened_at_ms=timestamp_ms - 60_000,
        correlation_group="BTCUSDT",
    )
    return PortfolioSnapshot(
        timestamp_ms=timestamp_ms,
        cash=9_900.0,
        equity=10_000.0,
        realized_pnl=0.0,
        total_fees=0.1,
        positions={"BTCUSDT": position},
    )


def _config() -> RegimeFilteredBreakoutConfig:
    return RegimeFilteredBreakoutConfig(
        breakout_window=3,
        exit_window=2,
        volatility_window=3,
        trend_window=2,
        volume_window=3,
        breakout_buffer_percent=0.05,
        minimum_volatility_percent=0.01,
        maximum_volatility_percent=10.0,
        minimum_trend_percent=0.10,
        volume_multiplier=1.0,
        maximum_hold_bars=3,
        cooldown_bars=2,
        requested_risk_percent=1.0,
        stop_loss_percent=5.0,
    )


def _warm(strategy: RegimeFilteredBreakoutStrategy) -> None:
    for index, (price, volume) in enumerate(
        ((100.0, 100.0), (101.0, 110.0), (100.5, 120.0), (101.5, 100.0)),
        start=1,
    ):
        assert strategy.on_market(
            _event(index * 60_000, price, volume=volume),
            _flat(index * 60_000),
        ) is None


def test_candidate_is_explicitly_separate_from_benchmarks() -> None:
    strategy = RegimeFilteredBreakoutStrategy(_config())

    assert strategy.candidate_name == "regime_filtered_breakout_v1"
    assert strategy.benchmark is False
    assert "volatility" in strategy.hypothesis
    assert strategy.config.to_dict()["volume_multiplier"] == 1.0


def test_entry_requires_prior_history_and_current_volume_confirmation() -> None:
    strategy = RegimeFilteredBreakoutStrategy(_config())
    _warm(strategy)

    low_volume = strategy.on_market(_event(300_000, 103.0, volume=50.0), _flat(300_000))
    assert low_volume is None

    strategy = RegimeFilteredBreakoutStrategy(_config())
    _warm(strategy)
    signal = strategy.on_market(_event(300_000, 103.0, volume=150.0), _flat(300_000))

    assert signal is not None
    assert signal.side is Side.BUY
    assert signal.reason == "alpha_regime_breakout_entry"
    assert signal.requested_risk_percent == 1.0
    assert signal.stop_loss_percent == 5.0


def test_current_breakout_does_not_mutate_prior_channel_before_decision() -> None:
    strategy = RegimeFilteredBreakoutStrategy(_config())
    _warm(strategy)

    signal = strategy.on_market(_event(300_000, 103.0, volume=150.0), _flat(300_000))

    assert signal is not None and signal.side is Side.BUY


def test_open_position_has_stop_and_time_based_exits() -> None:
    stop_strategy = RegimeFilteredBreakoutStrategy(_config())
    stop = stop_strategy.on_market(_event(60_000, 94.0), _long(60_000, entry_price=100.0))
    assert stop is not None
    assert stop.side is Side.SELL
    assert stop.reason == "alpha_regime_breakout_stop"

    time_strategy = RegimeFilteredBreakoutStrategy(_config())
    for timestamp in (60_000, 120_000):
        assert time_strategy.on_market(_event(timestamp, 101.0), _long(timestamp)) is None
    timed = time_strategy.on_market(_event(180_000, 101.0), _long(180_000))
    assert timed is not None
    assert timed.side is Side.SELL
    assert timed.reason == "alpha_regime_breakout_time_exit"


def test_cooldown_prevents_immediate_reentry_after_position_closes() -> None:
    strategy = RegimeFilteredBreakoutStrategy(_config())
    _warm(strategy)
    assert strategy.on_market(_event(300_000, 103.0, volume=150.0), _long(300_000)) is None
    assert strategy.on_market(_event(360_000, 106.0, volume=200.0), _flat(360_000)) is None
    assert strategy.on_market(_event(420_000, 108.0, volume=200.0), _flat(420_000)) is None


@pytest.mark.parametrize(
    ("metadata", "message"),
    (
        ({"market_type": "linear"}, "requires spot market events"),
        ({"timestamp_semantics": "point_in_time"}, "requires bar_close timestamps"),
        ({"price_source": "native_bid_ask"}, "requires close-derived price events"),
    ),
)
def test_strategy_itself_rejects_wrong_event_provenance(
    metadata: dict[str, object],
    message: str,
) -> None:
    strategy = RegimeFilteredBreakoutStrategy(_config())
    with pytest.raises(ValueError, match=message):
        strategy.on_market(_event(60_000, 100.0, metadata=metadata), _flat(60_000))


def test_strategy_itself_rejects_nonfinite_volume() -> None:
    strategy = RegimeFilteredBreakoutStrategy(_config())
    with pytest.raises(ValueError, match="finite non-negative volume"):
        strategy.on_market(_event(60_000, 100.0, volume=float("nan")), _flat(60_000))
