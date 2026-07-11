from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker


class FakeConnection:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = [json.dumps(item) for item in messages]
        self.sent: list[dict] = []

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def recv(self, timeout: float):
        if self.messages:
            return self.messages.pop(0)
        raise StopIteration


def test_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    worker = BybitWebSocketWorker()

    worker.start()

    assert worker.status()["enabled"] is False
    assert worker.status()["worker_running"] is False


def test_consumer_subscribes_and_ingests_verified_quote(monkeypatch):
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "1")
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_websocket_state.time.time", lambda: now_ms / 1000)
    worker = BybitWebSocketWorker()
    connection = FakeConnection([
        {"success": True, "op": "subscribe"},
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "ts": now_ms,
            "cs": 10,
            "data": {"symbol": "BTCUSDT", "lastPrice": "62000"},
        },
    ])

    with pytest.raises(StopIteration):
        worker._consume_connection(connection)

    assert connection.sent == [{"op": "subscribe", "args": ["tickers.BTCUSDT", "tickers.ETHUSDT"]}]
    quote = worker.state.current_quote("BTCUSDT", now_ms=now_ms)
    assert quote.price == 62000
    assert worker.status()["connected"] is True


def test_disconnected_worker_never_serves_cached_quote(monkeypatch):
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "1")
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_websocket_state.time.time", lambda: now_ms / 1000)
    worker = BybitWebSocketWorker()
    worker.state.mark_connected()
    worker.state.ingest_ticker({
        "topic": "tickers.BTCUSDT",
        "ts": now_ms,
        "cs": 1,
        "data": {"lastPrice": "62000"},
    }, received_at_ms=now_ms)
    worker.state.mark_disconnected("network lost")

    with pytest.raises(RuntimeError, match="disconnected"):
        worker.quote("BTCUSDT")


def test_symbol_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("BYBIT_WS_SYMBOLS", "BTCUSD,invalid-pair")

    with pytest.raises(ValueError, match="USDT"):
        BybitWebSocketWorker()
