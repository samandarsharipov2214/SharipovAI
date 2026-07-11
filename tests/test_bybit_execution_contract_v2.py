from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_execution import BybitExecutionClient, ExecutionResult
from exchange_connector.bybit_order_identity import OrderIntentRegistry


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {"retCode": 0, "result": {"orderId": "oid-1"}}
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or FakeResponse()

    def post(self, url, *, content, headers):
        self.calls.append((url, json.loads(content), headers))
        return self.response


def unlock_testnet(monkeypatch):
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("EXCHANGE_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "1000")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")


def client(tmp_path, monkeypatch, response=None):
    unlock_testnet(monkeypatch)
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    transport = FakeClient(response)
    return BybitExecutionClient(client=transport, intent_registry=registry), registry, transport


def test_execution_result_persists_identity_fields():
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
        candidate_id="candidate-001",
        attempt=1,
    )
    payload = result.to_dict()
    assert payload["category"] == "spot"
    assert payload["order_link_id"] == "sai_ts_abc"
    assert payload["candidate_id"] == "candidate-001"


def test_success_reserves_before_post_and_binds(tmp_path, monkeypatch):
    execution, registry, transport = client(tmp_path, monkeypatch)
    result = execution.place_market_order(
        candidate_id="candidate-001",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.01,
        reference_price=100,
    )
    assert result.order_link_id.startswith("sai_")
    assert result.candidate_id == "candidate-001"
    assert transport.calls[0][1]["orderLinkId"] == result.order_link_id
    record = registry.snapshot()["records"][0]
    assert record["status"] == "Submitted"
    assert record["exchange_order_id"] == "oid-1"

    with pytest.raises(RuntimeError, match="already reserved"):
        execution.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
        )
    assert len(transport.calls) == 1


def test_kill_switch_blocks_before_reservation(tmp_path, monkeypatch):
    execution, registry, transport = client(tmp_path, monkeypatch)
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    with pytest.raises(RuntimeError, match="kill switch"):
        execution.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
        )
    assert registry.snapshot()["tracked_intents"] == 0
    assert transport.calls == []


def test_definitive_reject_marks_reservation_rejected(tmp_path, monkeypatch):
    response = FakeResponse({"retCode": 10001, "retMsg": "bad", "result": {}})
    execution, registry, _ = client(tmp_path, monkeypatch, response)
    with pytest.raises(RuntimeError, match="rejected"):
        execution.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
        )
    assert registry.snapshot()["records"][0]["status"] == "Rejected"


def test_ambiguous_failure_leaves_unresolved_reservation(tmp_path, monkeypatch):
    response = FakeResponse(error=TimeoutError("timeout"))
    execution, registry, transport = client(tmp_path, monkeypatch, response)
    with pytest.raises(TimeoutError):
        execution.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
        )
    assert registry.snapshot()["records"][0]["status"] == "Reserved"
    with pytest.raises(RuntimeError, match="reconciliation"):
        execution.place_market_order(
            candidate_id="candidate-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            reference_price=100,
        )
    assert len(transport.calls) == 1
