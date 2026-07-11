from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_private_order_ws import BybitPrivateOrderWebSocket, validate_private_ws_url


class Store:
    def __init__(self): self.messages = []
    def ingest_message(self, payload, *, received_at_ms): self.messages.append((payload, received_at_ms)); return {"status": "ok"}
    def snapshot(self): return {"status": "ok", "orders": []}
    def reconcile(self, journal): return {"status": "ok", "restart_safe": True, "errors": []}


class Connection:
    def __init__(self, messages): self.messages = [json.dumps(item) for item in messages]; self.sent = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def send(self, value): self.sent.append(json.loads(value))
    def recv(self, *, timeout):
        if not self.messages: raise RuntimeError("disconnect")
        return self.messages.pop(0)


def configure(monkeypatch):
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "1")


def test_url_allowlist_and_default_off(monkeypatch) -> None:
    assert validate_private_ws_url("wss://stream-testnet.bybit.com/v5/private", environment="testnet").startswith("wss://")
    for value in ("ws://stream-testnet.bybit.com/v5/private", "wss://user@stream-testnet.bybit.com/v5/private", "wss://127.0.0.1/v5/private", "wss://stream.bybit.com/v5/private", "wss://stream-testnet.bybit.com:8443/v5/private", "wss://stream-testnet.bybit.com/v5/private?x=1"):
        with pytest.raises(ValueError): validate_private_ws_url(value, environment="testnet")
    monkeypatch.delenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", raising=False)
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    worker = BybitPrivateOrderWebSocket(store=Store(), connector=lambda *a, **k: None)
    worker.start()
    assert worker.status()["enabled"] is False and worker.status()["worker_running"] is False


def test_auth_subscribe_ingest_disconnect_and_redaction(monkeypatch) -> None:
    configure(monkeypatch)
    store = Store()
    order = {"id": "msg-1", "topic": "order", "creationTime": 1000, "data": [{"category": "spot", "orderId": "oid-1", "orderLinkId": "sai_123", "symbol": "BTCUSDT", "side": "Buy", "orderStatus": "New", "qty": "1", "cumExecQty": "0", "avgPrice": "0", "createdTime": "900", "updatedTime": "1000"}]}
    connection = Connection([
        {"op": "auth", "success": True, "req_id": "sharipovai-private-auth", "ret_msg": ""},
        {"op": "subscribe", "success": True, "req_id": "sharipovai-private-orders", "ret_msg": "", "data": {"successTopics": ["order"], "failTopics": []}},
        order,
    ])
    worker = BybitPrivateOrderWebSocket(store=store, connector=lambda *a, **k: connection, clock_ms=lambda: 1000)
    with pytest.raises(RuntimeError, match="disconnect"): worker.run_cycle()
    assert connection.sent[0]["op"] == "auth" and connection.sent[1]["args"] == ["order"]
    assert connection.sent[0]["args"][2] != "test-secret" and len(store.messages) == 1
    status_text = json.dumps(worker.status())
    assert "test-key" not in status_text and "test-secret" not in status_text
    assert worker.status()["connected"] is False


def test_negative_auth_and_disconnected_reconciliation_block(monkeypatch) -> None:
    configure(monkeypatch)
    store = Store()
    connection = Connection([{"op": "auth", "success": False, "ret_msg": "bad key"}])
    worker = BybitPrivateOrderWebSocket(store=store, connector=lambda *a, **k: connection, clock_ms=lambda: 1000)
    with pytest.raises(RuntimeError, match="authentication rejected"): worker.run_cycle()
    assert len(connection.sent) == 1 and store.messages == []
    result = worker.reconcile({"orders": []})
    assert result["restart_safe"] is False and "stream is not verified" in result["errors"][-1]


def test_incomplete_credentials_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "only-key")
    monkeypatch.delenv("BYBIT_TESTNET_API_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="incomplete"): BybitPrivateOrderWebSocket(store=Store())
