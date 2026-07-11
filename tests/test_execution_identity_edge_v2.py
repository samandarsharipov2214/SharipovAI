from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_execution import BybitExecutionClient
from exchange_connector.bybit_order_identity import OrderIntentRegistry


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"retCode": 0, "result": {"orderId": "oid-1"}}


class Transport:
    def __init__(self):
        self.calls = []

    def post(self, url, *, content, headers):
        self.calls.append(json.loads(content))
        return Response()


def unlock(monkeypatch):
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("EXCHANGE_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "1000")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")


def test_nonfinite_values_and_mismatched_link_block_before_reservation(tmp_path, monkeypatch):
    unlock(monkeypatch)
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    transport = Transport()
    client = BybitExecutionClient(transport, registry)

    with pytest.raises(ValueError, match="greater than zero"):
        client.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=float("nan"),
            reference_price=100,
        )
    assert registry.snapshot()["tracked_intents"] == 0

    with pytest.raises(RuntimeError, match="does not match"):
        client.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
            order_link_id="sai_wrong",
        )
    assert registry.snapshot()["tracked_intents"] == 0
    assert transport.calls == []
