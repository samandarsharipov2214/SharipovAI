from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.market_data_api import install_market_data_api
from exchange_connector.bybit_instrument_rules import (
    BybitInstrumentRulesService,
    InstrumentRulesUnavailable,
)


class FakeHTTP:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def get(self, url: str, params=None, timeout=None):
        self.calls += 1
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=self.payload, request=request)


def _spot_payload(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "status": "Trading",
        "priceFilter": {"tickSize": "0.10"},
        "lotSizeFilter": {
            "basePrecision": "0.000001",
            "minOrderQty": "0.000001",
            "minOrderAmt": "5",
            "maxLimitOrderQty": "100",
            "maxMarketOrderQty": "50",
        },
    }
    row.update(overrides)
    return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "list": [row]}}


def test_fetches_and_caches_verified_spot_rules(monkeypatch):
    fake = FakeHTTP(_spot_payload())
    service = BybitInstrumentRulesService(fake)
    monkeypatch.setattr(service, "ttl_seconds", 300.0)

    first = service.get("BTCUSDT", "spot")
    second = service.get("BTCUSDT", "spot")

    assert first.tick_size.as_tuple().exponent == -2
    assert str(first.qty_step) == "0.000001"
    assert str(first.min_notional) == "5"
    assert second == first
    assert fake.calls == 1


def test_rejects_wrong_symbol():
    fake = FakeHTTP(_spot_payload(symbol="ETHUSDT"))
    service = BybitInstrumentRulesService(fake)

    try:
        service.get("BTCUSDT", "spot")
    except InstrumentRulesUnavailable as exc:
        assert "different symbol" in str(exc)
    else:
        raise AssertionError("wrong-symbol response must fail closed")


def test_rejects_non_trading_instrument():
    fake = FakeHTTP(_spot_payload(status="PreLaunch"))
    service = BybitInstrumentRulesService(fake)

    try:
        service.get("BTCUSDT", "spot")
    except InstrumentRulesUnavailable as exc:
        assert "not tradable" in str(exc)
    else:
        raise AssertionError("non-trading instrument must fail closed")


def test_preview_rejects_manual_rule_override(monkeypatch):
    monkeypatch.setenv("FEATURE_BYBIT_PREVIEW_ENGINE", "1")
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "0")
    app = FastAPI()
    install_market_data_api(app)

    with TestClient(app) as client:
        response = client.post(
            "/api/trading/order-preview",
            json={
                "symbol": "BTCUSDT",
                "category": "spot",
                "side": "buy",
                "order_type": "limit",
                "quantity": "0.01",
                "reference_price": "60000",
                "limit_price": "60000",
                "stop_loss": "59000",
                "take_profit": "62000",
                "account_equity": "10000",
                "max_risk_percent": "2",
                "tick_size": "0.00000001",
            },
        )

    assert response.status_code == 400
    assert "manual instrument rules are forbidden" in response.json()["detail"]["message"]


def test_preview_uses_exchange_rules(monkeypatch):
    monkeypatch.setenv("FEATURE_BYBIT_PREVIEW_ENGINE", "1")
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "0")
    app = FastAPI()
    install_market_data_api(app)
    fake = FakeHTTP(_spot_payload())
    app.state.bybit_instrument_rules = BybitInstrumentRulesService(fake)

    with TestClient(app) as client:
        response = client.post(
            "/api/trading/order-preview",
            json={
                "symbol": "BTCUSDT",
                "category": "spot",
                "side": "buy",
                "order_type": "limit",
                "quantity": "0.01",
                "reference_price": "60000",
                "limit_price": "60000.04",
                "stop_loss": "59000",
                "take_profit": "62000",
                "account_equity": "10000",
                "max_risk_percent": "2",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["executed"] is False
    assert body["entry_price"] == 60000.1
    assert body["instrument_rules"]["source"] == "bybit_v5_instruments_info"
