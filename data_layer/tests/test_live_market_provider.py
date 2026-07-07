"""Tests for the live market provider."""

from __future__ import annotations

from bybit import BybitClientError, TickerInfo
from data_layer.providers import LiveMarketProvider


class _FakeBybitClient:
    """Fake async Bybit client for deterministic tests."""

    def __init__(self, tickers: list[TickerInfo] | None = None, fail: bool = False) -> None:
        """Initialize the fake client."""

        self.tickers = tickers or []
        self.fail = fail
        self.requested_category: str | None = None

    async def get_tickers(self, category: str = "spot") -> list[TickerInfo]:
        """Return configured tickers or raise a client error."""

        self.requested_category = category
        if self.fail:
            raise BybitClientError("client failed")
        return self.tickers


def test_live_market_provider_name() -> None:
    """Live market provider returns its name."""

    provider = LiveMarketProvider(client=_FakeBybitClient())

    assert provider.name() == "LiveMarketProvider"


def test_live_market_provider_fetches_spot_tickers() -> None:
    """Live market provider requests spot tickers."""

    client = _FakeBybitClient(tickers=[_ticker("BTCUSDT")])
    provider = LiveMarketProvider(client=client)
    provider.fetch()

    assert client.requested_category == "spot"


def test_live_market_provider_converts_tickers_to_data_items() -> None:
    """Live market provider converts ticker models into data items."""

    provider = LiveMarketProvider(client=_FakeBybitClient(tickers=[_ticker("BTCUSDT")]))
    batch = provider.fetch()

    assert len(batch.items) == 1
    item = batch.items[0]
    assert item.source == "bybit"
    assert item.category == "market"
    assert item.title == "BTCUSDT"
    assert "Last price: 50000" in item.content
    assert "24h change: 0.03" in item.content
    assert "24h turnover: 10000000" in item.content
    assert item.url is None
    assert item.published_at is None
    assert item.metadata == {
        "symbol": "BTCUSDT",
        "last_price": "50000",
        "price_24h_change_percent": "0.03",
        "turnover_24h": "10000000",
    }


def test_live_market_provider_handles_client_errors_gracefully() -> None:
    """Live market provider returns an empty batch when Bybit fails."""

    provider = LiveMarketProvider(client=_FakeBybitClient(fail=True))
    batch = provider.fetch()

    assert batch.items == []


def test_live_market_provider_handles_empty_tickers() -> None:
    """Live market provider returns an empty batch for empty ticker lists."""

    provider = LiveMarketProvider(client=_FakeBybitClient(tickers=[]))
    batch = provider.fetch()

    assert batch.items == []


def _ticker(symbol: str) -> TickerInfo:
    """Create a ticker fixture."""

    return TickerInfo(
        category="spot",
        symbol=symbol,
        last_price="50000",
        bid_price="49990",
        ask_price="50010",
        price_24h_change_percent="0.03",
        volume_24h="2000",
        turnover_24h="10000000",
    )
