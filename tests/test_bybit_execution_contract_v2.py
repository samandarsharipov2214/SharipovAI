from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_execution import BybitExecutionClient, ExecutionResult


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"retCode": 0, "result": {"orderId": "oid-1"}}


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, *, content, headers):
        self.calls.append((url, json.loads(content), headers))
        return FakeResponse()


def unlock_testnet(monkeypatch):
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("EXCHANGE_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "1000")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")


def test_execution_result_persists_category_and_order_link_id():
    result = ExecutionResult(
        status="accepted",
        mode="sandbox",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.01,
        order_id="oid-1",
        message="ok",
        raw_code=0,
        category="spot",
        order_link_id="sai_ts_abc",
    )
    payload = result.to_dict()
    assert payload["category"] == "spot"
    assert payload["order_link_id"] == "sai_ts_abc"


def test_unlocked_execution_requires_deterministic_order_link_id(monkeypatch):
    unlock_testnet(monkeypatch)
    client = BybitExecutionClient(client=FakeClient())
    with pytest.raises(RuntimeError, match="orderLinkId reservation is required"):
        client.place_market_order(
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
        )


def test_order_link_id_is_sent_and_recorded(monkeypatch):
    unlock_testnet(monkeypatch)
    transport = FakeClient()
    client = BybitExecutionClient(client=transport)
    result = client.place_market_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.01,
        reference_price=100,
        order_link_id="sai_ts_abc",
    )
    assert result.category == "spot"
    assert result.order_link_id == "sai_ts_abc"
    assert transport.calls[0][1]["category"] == "spot"
    assert transport.calls[0][1]["orderLinkId"] == "sai_ts_abc"
