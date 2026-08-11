"""Research-integrity contract for historical MarketEvent price provenance."""
from __future__ import annotations

from types import SimpleNamespace

from historical_data.loader import HistoricalDataLoader


def _loader(default_spread_bps: float = 2.0) -> HistoricalDataLoader:
    loader = HistoricalDataLoader.__new__(HistoricalDataLoader)
    loader.manifest = SimpleNamespace(default_spread_bps=default_spread_bps)
    return loader


def test_native_bid_ask_is_classified_as_native_quote_source() -> None:
    bid_sql, ask_sql, price_source = _loader()._price_expressions({"bid", "ask"})

    assert bid_sql == "CAST(bid AS DOUBLE)"
    assert ask_sql == "CAST(ask AS DOUBLE)"
    assert price_source == "native_bid_ask"


def test_close_only_dataset_is_explicitly_marked_synthetic() -> None:
    bid_sql, ask_sql, price_source = _loader(10.0)._price_expressions({"close"})

    assert "close" in bid_sql
    assert "close" in ask_sql
    assert bid_sql != ask_sql
    assert price_source == "synthetic_from_close"


def test_missing_executable_price_columns_remains_fail_closed() -> None:
    import pytest

    with pytest.raises(ValueError, match="requires bid\\+ask or close"):
        _loader()._price_expressions({"volume"})
