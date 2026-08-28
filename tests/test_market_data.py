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
                    "list": [{
                        "symbol": "BTCUSDT",
                        "lastPrice": "60000.5", "price24hPcnt": "0.025", "turnover24h": "1000000",
                        "bid1Price": "60000.0", "ask1Price": "60001.0",
                    }]
                },
            },
        )

    quote = MarketDataService(client=_client(handler)).quote("btc/usdt")
    assert quote.symbol == "BTCUSDT"
    assert quote.price == 60000.5
    assert quote.change_24h_percent == 2.5
    assert quote.source == "bybit"
    assert quote.verified is True
    assert quote.bid_price == 60000.0
    assert quote.ask_price == 60001.0


def test_binance_is_used_when_bybit_fails() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if "bybit.com" in request.url.host:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(
            200,
            json={
                "symbol": "ETHUSDT",
                "lastPrice": "3000", "priceChangePercent": "1.2", "quoteVolume": "500000",
                "bidPrice": "2999.5", "askPrice": "3000.5",
            },
        )

    quote = MarketDataService(client=_client(handler)).quote("ETH-USDT")
    assert calls == 2
    assert quote.source == "binance"
    assert quote.price == 3000.0
    assert quote.bid_price == 2999.5
    assert quote.ask_price == 3000.5


def test_crossed_bybit_bbo_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "result": {"list": [{
                    "symbol": "BTCUSDT",
                    "lastPrice": "100", "price24hPcnt": "0", "turnover24h": "1000",
                    "bid1Price": "101", "ask1Price": "100",
                }]},
            },
        )

    with pytest.raises(ValueError, match="best ask"):
        MarketDataService(client=_client(handler)).provider_quote("bybit", "BTCUSDT")


def test_provider_symbol_mismatch_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "result": {"list": [{
                    "symbol": "ETHUSDT",
                    "lastPrice": "100", "price24hPcnt": "0", "turnover24h": "1000",
                    "bid1Price": "99", "ask1Price": "101",
                }]},
            },
        )

    with pytest.raises(ValueError, match="different symbol"):
        MarketDataService(client=_client(handler)).provider_quote("bybit", "BTCUSDT")


def test_no_provider_means_no_fake_price() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    with pytest.raises(MarketDataUnavailable, match="no synthetic fallback used"):
        MarketDataService(client=_client(handler)).quote("BTCUSDT")


def test_invalid_symbol_is_rejected_before_network() -> None:
    service = MarketDataService(client=_client(lambda _request: pytest.fail("network must not be called")))
    with pytest.raises(ValueError):
        service.quote("BTC USDT!")
