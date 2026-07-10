from __future__ import annotations

import httpx
import pytest

from exchange_connector.market_data import MarketDataService, MarketDataUnavailable


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_bybit_quote_is_verified_and_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["symbol"] == "BTCUSDT"
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "result": {
                    "list": [{"lastPrice": "60000.5", "price24hPcnt": "0.025", "turnover24h": "1000000"}]
                },
            },
        )

    quote = MarketDataService(client=_client(handler)).quote("btc/usdt")
    assert quote.symbol == "BTCUSDT"
    assert quote.price == 60000.5
    assert quote.change_24h_percent == 2.5
    assert quote.source == "bybit"
    assert quote.verified is True


def test_binance_is_used_when_bybit_fails() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if "bybit.com" in request.url.host:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(
            200,
            json={"lastPrice": "3000", "priceChangePercent": "1.2", "quoteVolume": "500000"},
        )

    quote = MarketDataService(client=_client(handler)).quote("ETH-USDT")
    assert calls == 2
    assert quote.source == "binance"
    assert quote.price == 3000.0


def test_no_provider_means_no_fake_price() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    with pytest.raises(MarketDataUnavailable, match="no synthetic fallback used"):
        MarketDataService(client=_client(handler)).quote("BTCUSDT")


def test_invalid_symbol_is_rejected_before_network() -> None:
    service = MarketDataService(client=_client(lambda _request: pytest.fail("network must not be called")))
    with pytest.raises(ValueError):
        service.quote("BTC USDT!")
