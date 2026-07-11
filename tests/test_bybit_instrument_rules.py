from __future__ import annotations

import httpx
import pytest

from exchange_connector.bybit_instrument_rules import (
    BybitInstrumentRulesService,
    InstrumentRulesUnavailable,
)
from exchange_connector.bybit_preflight import BybitPreflightError


def _response(row: dict, *, category: str = "spot") -> httpx.Response:
    request = httpx.Request("GET", "https://api.bybit.com/v5/market/instruments-info")
    return httpx.Response(
        200,
        request=request,
        json={"retCode": 0, "retMsg": "OK", "result": {"category": category, "list": [row]}},
    )


class _Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, url, params, timeout):
        self.calls += 1
        return next(self.responses)


def _spot_row(**changes):
    row = {
        "symbol": "BTCUSDT",
        "status": "Trading",
        "baseCoin": "BTC",
        "quoteCoin": "USDT",
        "priceFilter": {"tickSize": "0.1"},
        "lotSizeFilter": {
            "basePrecision": "0.000001",
            "minOrderQty": "999",
            "minOrderAmt": "5",
            "maxLimitOrderQty": "83",
            "maxMarketOrderQty": "41.5",
        },
    }
    row.update(changes)
    return row


def _linear_row(**changes):
    row = {
        "symbol": "BTCUSDT",
        "status": "Trading",
        "baseCoin": "BTC",
        "quoteCoin": "USDT",
        "priceFilter": {"tickSize": "0.1", "minPrice": "0.1", "maxPrice": "2000000"},
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "minNotionalValue": "5",
            "maxOrderQty": "1190",
            "maxMktOrderQty": "500",
        },
        "leverageFilter": {"minLeverage": "1", "maxLeverage": "100", "leverageStep": "0.01"},
    }
    row.update(changes)
    return row


def test_public_base_url_must_be_official_https(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://evil.example")
    with pytest.raises(BybitPreflightError):
        BybitInstrumentRulesService()


def test_spot_uses_base_precision_and_current_min_order_amount(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
    client = _Client([_response(_spot_row())])
    rules = BybitInstrumentRulesService(client=client).get("BTCUSDT", "spot")
    assert str(rules.qty_step) == "0.000001"
    assert rules.min_qty == rules.qty_step
    assert str(rules.min_notional) == "5"
    assert str(rules.max_limit_qty) == "83"
    assert str(rules.max_market_qty) == "41.5"
    assert rules.max_leverage is None


def test_linear_rules_include_price_quantity_and_leverage_limits(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
    rules = BybitInstrumentRulesService(client=_Client([_response(_linear_row(), category="linear")])).get(
        "BTCUSDT", "linear"
    )
    assert str(rules.tick_size) == "0.1"
    assert str(rules.qty_step) == "0.001"
    assert str(rules.min_price) == "0.1"
    assert str(rules.max_price) == "2000000"
    assert str(rules.max_leverage) == "100"
    assert rules.preview_fields("market")["max_qty"] == "500"
    assert rules.preview_fields("limit")["max_qty"] == "1190"


def test_cache_prevents_repeated_network_calls(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
    client = _Client([_response(_spot_row())])
    service = BybitInstrumentRulesService(client=client)
    first = service.get("BTCUSDT", "spot")
    second = service.get("BTCUSDT", "spot")
    assert first == second
    assert client.calls == 1


def test_wrong_symbol_category_or_non_trading_status_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
    cases = [
        _response(_spot_row(symbol="ETHUSDT")),
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.bybit.com/v5/market/instruments-info"),
            json={"retCode": 0, "result": {"category": "linear", "list": [_spot_row()]}},
        ),
        _response(_spot_row(status="PreLaunch")),
    ]
    for response in cases:
        service = BybitInstrumentRulesService(client=_Client([response]))
        with pytest.raises(InstrumentRulesUnavailable):
            service.get("BTCUSDT", "spot")


def test_non_finite_or_contradictory_limits_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
    rows = [
        _spot_row(priceFilter={"tickSize": "nan"}),
        _spot_row(lotSizeFilter={**_spot_row()["lotSizeFilter"], "maxMarketOrderQty": "0.0000001"}),
        _linear_row(leverageFilter={"minLeverage": "10", "maxLeverage": "5", "leverageStep": "1"}),
    ]
    categories = ["spot", "spot", "linear"]
    for row, category in zip(rows, categories):
        service = BybitInstrumentRulesService(client=_Client([_response(row, category=category)]))
        with pytest.raises(InstrumentRulesUnavailable):
            service.get("BTCUSDT", category)


def test_cache_ttl_has_hard_cap(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
    monkeypatch.setenv("BYBIT_INSTRUMENT_CACHE_TTL_SECONDS", "999999")
    service = BybitInstrumentRulesService(client=_Client([]))
    assert service.ttl_seconds == 900.0
