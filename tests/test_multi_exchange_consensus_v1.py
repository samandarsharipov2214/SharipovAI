from __future__ import annotations

from datetime import UTC, datetime

import pytest

from exchange_connector.market_data import MarketQuote
from exchange_connector.multi_exchange_consensus import ConsensusUnavailable, MultiExchangeConsensus


def _quote(source: str, price: float) -> MarketQuote:
    now = datetime.now(UTC)
    return MarketQuote(
        symbol="BTCUSDT",
        price=price,
        change_24h_percent=None,
        volume_24h=None,
        source=source,
        source_url=f"https://{source}.example",
        received_at=now.isoformat(),
        received_at_unix_ms=int(now.timestamp() * 1000),
    )


def test_consensus_uses_median_and_rejects_outlier(monkeypatch):
    consensus = MultiExchangeConsensus()
    providers = [
        ("bybit", lambda symbol: _quote("bybit", 100.00)),
        ("binance", lambda symbol: _quote("binance", 100.10)),
        ("okx", lambda symbol: _quote("okx", 99.95)),
        ("kraken", lambda symbol: _quote("kraken", 100.05)),
        ("coinbase", lambda symbol: _quote("coinbase", 120.00)),
    ]
    monkeypatch.setattr(consensus, "_providers", lambda: providers)

    result = consensus.quote("BTCUSDT")

    assert result.verified is True
    assert result.source_count == 4
    assert result.price == pytest.approx(100.025)
    assert result.rejected_sources == ("coinbase",)
    assert set(result.sources) == {"bybit", "binance", "okx", "kraken"}


def test_consensus_blocks_when_fewer_than_three_sources(monkeypatch):
    consensus = MultiExchangeConsensus()

    def failed(symbol):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        consensus,
        "_providers",
        lambda: [
            ("bybit", lambda symbol: _quote("bybit", 100)),
            ("binance", lambda symbol: _quote("binance", 100.1)),
            ("okx", failed),
            ("kraken", failed),
            ("coinbase", failed),
        ],
    )

    with pytest.raises(ConsensusUnavailable, match="insufficient independent quotes"):
        consensus.quote("BTCUSDT")


def test_consensus_blocks_when_prices_do_not_agree(monkeypatch):
    consensus = MultiExchangeConsensus()
    monkeypatch.setenv("MARKET_CONSENSUS_MAX_DEVIATION_PERCENT", "0.10")
    consensus = MultiExchangeConsensus()
    monkeypatch.setattr(
        consensus,
        "_providers",
        lambda: [
            ("bybit", lambda symbol: _quote("bybit", 100)),
            ("binance", lambda symbol: _quote("binance", 101)),
            ("okx", lambda symbol: _quote("okx", 102)),
            ("kraken", lambda symbol: _quote("kraken", 103)),
            ("coinbase", lambda symbol: _quote("coinbase", 104)),
        ],
    )

    with pytest.raises(ConsensusUnavailable, match="price disagreement"):
        consensus.quote("BTCUSDT")


def test_consensus_feature_flag_is_disabled_by_default(monkeypatch):
    from config.feature_flags import is_feature_enabled

    monkeypatch.delenv("FEATURE_MULTI_EXCHANGE_CONSENSUS", raising=False)
    assert is_feature_enabled("multi_exchange_consensus") is False
