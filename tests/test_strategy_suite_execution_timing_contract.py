"""Execution-timing gate for strategy evidence."""
from __future__ import annotations

import pytest

from trading_core.models import MarketEvent
from trading_core.strategy_suite import _validate_market_event_execution_semantics


def _event(*, price_source: str | None, dataset: bool = True, semantics: str | None = None) -> MarketEvent:
    metadata: dict[str, object] = {}
    if dataset:
        metadata["dataset_id"] = "dataset-v1"
    if price_source is not None:
        metadata["price_source"] = price_source
    if semantics is not None:
        metadata["timestamp_semantics"] = semantics
        metadata["interval_ms"] = 60_000
    return MarketEvent(
        timestamp_ms=1,
        symbol="BTCUSDT",
        bid=99.9,
        ask=100.1,
        metadata=metadata,
    )


def test_native_bid_ask_historical_events_pass_timing_gate() -> None:
    _validate_market_event_execution_semantics(
        (_event(price_source="native_bid_ask"),)
    )


def test_close_derived_historical_events_require_explicit_bar_close_semantics() -> None:
    with pytest.raises(ValueError, match="interval_ms"):
        _validate_market_event_execution_semantics(
            (_event(price_source="synthetic_from_close"),)
        )


def test_close_derived_bar_close_events_pass_with_next_event_contract() -> None:
    _validate_market_event_execution_semantics(
        (_event(price_source="synthetic_from_close", semantics="bar_close"),)
    )


def test_historical_dataset_without_price_provenance_fails_closed() -> None:
    with pytest.raises(ValueError, match="explicit market-event price provenance"):
        _validate_market_event_execution_semantics(
            (_event(price_source=None),)
        )


def test_manual_point_in_time_fixture_without_dataset_metadata_remains_compatible() -> None:
    _validate_market_event_execution_semantics(
        (_event(price_source=None, dataset=False),)
    )
