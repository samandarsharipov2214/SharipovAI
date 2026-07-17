from __future__ import annotations

import httpx
import pytest

from exchange_connector.bybit_reference_data import BybitTradingReferenceClient
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")


def test_dynamic_fee_and_spot_instrument_rules_are_cached_and_normalized(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v5/account/fee-rate":
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "makerFeeRate": "0.0001",
                                "takerFeeRate": "0.0006",
                            }
                        ]
                    },
                },
            )
        if request.url.path == "/v5/market/instruments-info":
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "category": "spot",
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "status": "Trading",
                                "baseCoin": "BTC",
                                "quoteCoin": "USDT",
                                "priceFilter": {"tickSize": "0.01"},
                                "lotSizeFilter": {
                                    "basePrecision": "0.0001",
                                    "minOrderQty": "0.0001",
                                    "minOrderAmt": "5",
                                    "maxMarketOrderQty": "10",
                                },
                            }
                        ],
                    },
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reference = BybitTradingReferenceClient(
        client,
        database=_database(tmp_path),
        environment="sandbox",
        ttl_seconds=300,
    )

    snapshot = reference.get("BTCUSDT", category="spot", now_ms=1_000_000)
    assert snapshot.fee.taker_fee_rate == pytest.approx(0.0006)
    assert snapshot.instrument.quantity_step == pytest.approx(0.0001)
    assert snapshot.instrument.minimum_notional == pytest.approx(5.0)
    assert snapshot.instrument.normalize_quantity(
        requested_quantity=1.0,
        reference_price=50_000.0,
        maximum_notional=25.0,
    ) == pytest.approx(0.0005)

    cached = reference.get(
        "BTCUSDT",
        category="spot",
        allow_network=False,
        now_ms=1_000_100,
    )
    assert cached.to_dict() == snapshot.to_dict()
    assert calls.count("/v5/account/fee-rate") == 1
    assert calls.count("/v5/market/instruments-info") == 1


def test_quantity_below_exchange_minimum_is_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v5/account/fee-rate":
            return httpx.Response(200, json={"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "makerFeeRate": "0.0001", "takerFeeRate": "0.0006"}]}})
        return httpx.Response(200, json={"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "status": "Trading", "baseCoin": "BTC", "quoteCoin": "USDT", "priceFilter": {"tickSize": "0.01"}, "lotSizeFilter": {"basePrecision": "0.001", "minOrderQty": "0.001", "minOrderAmt": "50", "maxMarketOrderQty": "10"}}]}})

    reference = BybitTradingReferenceClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        database=_database(tmp_path),
        environment="sandbox",
    )
    snapshot = reference.get("BTCUSDT", now_ms=1_000_000)
    with pytest.raises(ValueError, match="minimum"):
        snapshot.instrument.normalize_quantity(
            requested_quantity=1.0,
            reference_price=10_000.0,
            maximum_notional=25.0,
        )
