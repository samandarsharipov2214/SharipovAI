from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_private_order_ws import (
    BybitPrivateOrderWebSocket,
    validate_private_ws_url,
)


class Store:
    def __init__(self) -> None:
        self.messages: list[tuple[dict, int]] = []

    def ingest_message(self, payload, *, received_at_ms):
        self.messages.append((payload, received_at_ms))
        return {"status": "ok"}

    def snapshot(self):
        return {"status": "ok", "orders": [], "managed_orders": []}

    def reconcile(self, journal):
        return {"status": "ok", "restart_safe": True, "errors": []}


class ExecutionStore:
    def __init__(self) -> None:
        self.messages: list[tuple[dict, int]] = []

    def ingest_message(self, payload, *, received_at_ms):
        self.messages.append((payload, received_at_ms))
        return {"status": "ok"}

    def snapshot(self):
        return {
            "status": "ok",
            "fills": [],
            "managed_fills": [],
            "managed_orders": [],
            "execution_count": 0,
            "managed_execution_count": 0,
            "deduplicated_replay_count": 0,
            "conflicting_duplicate_count": 0,
        }

    def reconcile(self, order_snapshot):
        assert "managed_orders" in order_snapshot
        return {
            "status": "ok",
            "restart_safe": True,
            "errors": [],
            "orphan_execution_links": [],
            "missing_execution_links": [],
            "quantity_mismatch_links": [],
            "conflicting_duplicate_count": 0,
            "deduplicated_replay_count": 0,
        }


class Connection:
    def __init__(self, messages) -> None:
        self.messages = [json.dumps(item) for item in messages]
        self.sent: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send(self, value):
        self.sent.append(json.loads(value))

    def recv(self, *, timeout):
        if not self.messages:
            raise RuntimeError("disconnect")
        return self.messages.pop(0)


def configure(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "1")


def test_url_allowlist_and_default_off(monkeypatch) -> None:
    assert validate_private_ws_url(
        "wss://stream-testnet.bybit.com/v5/private",
        environment="testnet",
    ).startswith("wss://")
    for value in (
        "ws://stream-testnet.bybit.com/v5/private",
        "wss://user@stream-testnet.bybit.com/v5/private",
        "wss://127.0.0.1/v5/private",
        "wss://stream.bybit.com/v5/private",
        "wss://stream-testnet.bybit.com:8443/v5/private",
        "wss://stream-testnet.bybit.com/v5/private?x=1",
    ):
        with pytest.raises(ValueError):
            validate_private_ws_url(value, environment="testnet")
    monkeypatch.delenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", raising=False)
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    worker = BybitPrivateOrderWebSocket(
        store=Store(),
        execution_store=ExecutionStore(),
        connector=lambda *a, **k: None,
    )
    worker.start()
    assert worker.status()["enabled"] is False
    assert worker.status()["worker_running"] is False


def test_auth_subscribe_ingest_disconnect_and_redaction(monkeypatch) -> None:
    configure(monkeypatch)
    store = Store()
    executions = ExecutionStore()
    order = {
        "id": "msg-1",
        "topic": "order",
        "creationTime": 1000,
        "data": [
            {
                "category": "spot",
                "orderId": "oid-1",
                "orderLinkId": "sai_123",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "orderStatus": "New",
                "qty": "1",
                "cumExecQty": "0",
                "avgPrice": "0",
                "createdTime": "900",
                "updatedTime": "1000",
            }
        ],
    }
    connection = Connection(
        [
            {
                "op": "auth",
                "success": True,
                "req_id": "sharipovai-private-auth",
                "ret_msg": "",
            },
            {
                "op": "subscribe",
                "success": True,
                "req_id": "sharipovai-private-order-execution",
                "ret_msg": "",
                "data": {
                    "successTopics": ["order", "execution"],
                    "failTopics": [],
                },
            },
            order,
        ]
    )
    worker = BybitPrivateOrderWebSocket(
        store=store,
        execution_store=executions,
        connector=lambda *a, **k: connection,
        clock_ms=lambda: 1000,
    )
    with pytest.raises(RuntimeError, match="disconnect"):
        worker.run_cycle()
    assert connection.sent[0]["op"] == "auth"
    assert connection.sent[1]["args"] == ["execution", "order"]
    assert connection.sent[0]["args"][2] != "test-secret"
    assert len(store.messages) == 1
    assert executions.messages == []
    status_text = json.dumps(worker.status())
    assert "test-key" not in status_text
    assert "test-secret" not in status_text
    assert worker.status()["connected"] is False


def test_negative_auth_and_disconnected_reconciliation_block(monkeypatch) -> None:
    configure(monkeypatch)
    store = Store()
    executions = ExecutionStore()
    connection = Connection(
        [{"op": "auth", "success": False, "ret_msg": "bad key"}]
    )
    worker = BybitPrivateOrderWebSocket(
        store=store,
        execution_store=executions,
        connector=lambda *a, **k: connection,
        clock_ms=lambda: 1000,
    )
    with pytest.raises(RuntimeError, match="authentication rejected"):
        worker.run_cycle()
    assert len(connection.sent) == 1
    assert store.messages == []
    assert executions.messages == []
    result = worker.reconcile({"orders": []})
    assert result["restart_safe"] is False
    assert "private_order_stream_disconnected" in result["errors"]


def test_incomplete_credentials_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "only-key")
    monkeypatch.delenv("BYBIT_TESTNET_API_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="incomplete"):
        BybitPrivateOrderWebSocket(
            store=Store(),
            execution_store=ExecutionStore(),
        )
