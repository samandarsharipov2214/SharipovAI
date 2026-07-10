from __future__ import annotations

import httpx
import pytest

from exchange_connector.market_data import MarketDataService, MarketDataUnavailable


def _response_for(request: httpx.Request, prices: dict[str, float], failures: set[str] | None = None) -> httpx.Response:
    failures = failures or set()
    host = request.url.host or ""
    if "bybit" in host:
        name = "bybit"
        if name in failures:
            return httpx.Response(503, json={"error": "down"})
        price = prices[name]
        return httpx.Response(200, json={"retCode": 0, "result": {"list": [{"lastPrice": str(price), "price24hPcnt": "0.01", "turnover24h": "1000"}]}})
    if "binance" in host:
        name = "binance"
        if name in failures:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(200, json={"lastPrice": str(prices[name]), "priceChangePercent": "1", "quoteVolume": "1000"})
    if "okx" in host:
        name = "okx"
        if name in failures:
            return httpx.Response(503, json={"error": "down"})
        price = prices[name]
        return httpx.Response(200, json={"code": "0", "data": [{"last": str(price), "open24h": str(price / 1.01), "volCcy24h": "1000"}]})
    if "kraken" in host:
        name = "kraken"
        if name in failures:
            return httpx.Response(503, json={"error": "down"})
        price = prices[name]
        return httpx.Response(200, json={"error": [], "result": {"XBTUSDT": {"c": [str(price)], "o": str(price / 1.01), "v": ["1", "2"]}}})
    if "coinbase" in host:
        name = "coinbase"
        if name in failures:
            return httpx.Response(503, json={"error": "down"})
        price = prices[name]
        return httpx.Response(200, json={"last": str(price), "open": str(price / 1.01), "volume": "1000"})
    raise AssertionError(f"unexpected host {host}")


def _service(prices: dict[str, float], failures: set[str] | None = None) -> MarketDataService:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: _response_for(request, prices, failures)))
    return MarketDataService(client=client, cache_ttl_seconds=0, minimum_consensus_sources=3, maximum_deviation_percent=0.75)


def test_consensus_uses_all_five_consistent_exchanges() -> None:
    service = _service({"bybit": 100.0, "binance": 100.1, "okx": 99.9, "kraken": 100.05, "coinbase": 100.0})
    quote = service.consensus_quote("BTCUSDT")
    assert quote.verified is True
    assert len(quote.constituents) == 5
    assert quote.price == pytest.approx(100.0)
    assert quote.deviation_percent is not None
    assert quote.deviation_percent < 0.2


def test_outlier_exchange_is_rejected_from_consensus() -> None:
    service = _service({"bybit": 100.0, "binance": 100.1, "okx": 99.9, "kraken": 100.05, "coinbase": 130.0})
    quote = service.consensus_quote("BTCUSDT")
    sources = {item["source"] for item in quote.constituents}
    assert "coinbase" not in sources
    assert len(sources) == 4
    assert quote.price < 101


def test_three_online_exchanges_are_enough_but_health_reports_two_offline() -> None:
    prices = {"bybit": 100.0, "binance": 100.1, "okx": 99.9, "kraken": 100.0, "coinbase": 100.0}
    service = _service(prices, {"kraken", "coinbase"})
    snapshot = service.all_quotes("BTCUSDT")
    quote = service.consensus_quote("BTCUSDT")
    assert snapshot["online_count"] == 3
    assert snapshot["offline_count"] == 2
    assert len(quote.constituents) == 3


def test_fewer_than_three_exchanges_blocks_consensus_without_fake_price() -> None:
    prices = {"bybit": 100.0, "binance": 100.1, "okx": 99.9, "kraken": 100.0, "coinbase": 100.0}
    service = _service(prices, {"okx", "kraken", "coinbase"})
    with pytest.raises(MarketDataUnavailable, match="minimum 3"):
        service.consensus_quote("BTCUSDT")
