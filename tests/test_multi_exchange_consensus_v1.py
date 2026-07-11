from __future__ import annotations

import math
import time

import pytest

from exchange_connector.market_data import MarketQuote, positive_finite_float
from exchange_connector.multi_exchange_consensus import (
    ConsensusUnavailable,
    MultiExchangeConsensus,
)


def _quote(source: str, price: float, symbol: str = "BTCUSDT") -> MarketQuote:
    now = int(time.time() * 1000)
    return MarketQuote(
        symbol=symbol,
        price=price,
        change_24h_percent=None,
        volume_24h=None,
        source=source,
        source_url=f"https://{source}.example/public",
        received_at="2026-07-11T00:00:00+00:00",
        received_at_unix_ms=now,
    )


class _Consensus(MultiExchangeConsensus):
    def __init__(self, values):
        super().__init__(service=object())
        self.values = values

    def _providers(self):
        result = []
        for source, value in self.values.items():
            def provider(symbol, source=source, value=value):
                if isinstance(value, BaseException):
                    raise value
                if callable(value):
                    return value(symbol)
                return _quote(source, value, symbol)
            result.append((source, provider))
        return result


def test_median_consensus_requires_three_independent_sources(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_CONSENSUS_MIN_SOURCES", "3")
    consensus = _Consensus(
        {"bybit": 100.0, "binance": 100.1, "okx": 99.9, "kraken": 100.05, "coinbase": 100.0}
    ).quote("BTCUSDT")
    assert consensus.verified is True
    assert consensus.price == 100.0
    assert consensus.source_count == 5
    assert consensus.rejected_sources == ()


def test_outlier_and_failed_provider_are_preserved_as_evidence(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_CONSENSUS_MAX_DEVIATION_PERCENT", "0.35")
    result = _Consensus(
        {
            "bybit": 100.0,
            "binance": 100.1,
            "okx": 99.9,
            "kraken": 130.0,
            "coinbase": RuntimeError("provider offline"),
        }
    ).quote("BTCUSDT")
    assert result.source_count == 3
    assert set(result.rejected_sources) == {"coinbase", "kraken"}
    assert "outlier" in result.rejection_reasons["kraken"]
    assert "provider offline" in result.rejection_reasons["coinbase"]


def test_insufficient_sources_or_disagreement_fails_closed() -> None:
    with pytest.raises(ConsensusUnavailable, match="insufficient"):
        _Consensus({"bybit": 100.0, "binance": 100.1, "okx": RuntimeError("down")}).quote("BTCUSDT")

    with pytest.raises(ConsensusUnavailable, match="disagreement"):
        _Consensus(
            {"bybit": 100.0, "binance": 110.0, "okx": 120.0, "kraken": 130.0, "coinbase": 140.0}
        ).quote("BTCUSDT")


def test_non_finite_prices_are_rejected() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            positive_finite_float(value, "price")

    with pytest.raises(ConsensusUnavailable):
        _Consensus(
            {"bybit": 100.0, "binance": math.nan, "okx": math.inf, "kraken": 100.1, "coinbase": -math.inf}
        ).quote("BTCUSDT")


def test_only_usdt_spot_symbols_are_accepted() -> None:
    consensus = _Consensus({"bybit": 100.0, "binance": 100.0, "okx": 100.0})
    for symbol in ("BTCUSD", "USDT", "BTC-EUR", ""):
        with pytest.raises(ValueError, match="USDT"):
            consensus.quote(symbol)


def test_environment_thresholds_have_hard_safe_caps(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_CONSENSUS_MIN_SOURCES", "1")
    monkeypatch.setenv("MARKET_CONSENSUS_MAX_DEVIATION_PERCENT", "999")
    consensus = _Consensus({"bybit": 100.0, "binance": 100.0, "okx": 100.0})
    assert consensus.minimum_sources == 3
    assert consensus.max_deviation_percent == 2.0
