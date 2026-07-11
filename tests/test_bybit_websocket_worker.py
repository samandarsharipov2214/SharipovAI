from __future__ import annotations

import json
import time

import pytest

from exchange_connector.bybit_websocket_worker import (
    BybitWebSocketWorker,
    validate_public_ws_url,
)


class _Connection:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def recv(self, timeout: float):
        value = next(self.messages)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value)


def _connector(connection: _Connection):
    def connect(*args, **kwargs):
        return connection

    return connect


def _ack(**changes):
    payload = {
        "success": True,
        "ret_msg": "subscribe",
        "op": "subscribe",
        "req_id": "sharipovai-public-tickers",
    }
    payload.update(changes)
    return payload


def _ticker():
    now = int(time.time() * 1000)
    return {
        "topic": "tickers.BTCUSDT",
        "type": "snapshot",
        "ts": now,
        "cs": now,
        "data": {"symbol": "BTCUSDT", "lastPrice": "64000"},
    }


def test_official_mainnet_spot_urls_are_allowed() -> None:
    assert validate_public_ws_url("wss://stream.bybit.com/v5/public/spot") == "wss://stream.bybit.com/v5/public/spot"
    assert validate_public_ws_url("wss://stream.bybit.tr/v5/public/spot/") == "wss://stream.bybit.tr/v5/public/spot"


@pytest.mark.parametrize(
    "url",
    [
        "ws://stream.bybit.com/v5/public/spot",
        "wss://user@stream.bybit.com/v5/public/spot",
        "wss://stream.bybit.com:8443/v5/public/spot",
        "wss://stream.bybit.com/v5/private",
        "wss://stream.bybit.com/v5/public/spot?x=1",
        "wss://stream-testnet.bybit.com/v5/public/spot",
        "wss://127.0.0.1/v5/public/spot",
        "wss://evil.example/v5/public/spot",
    ],
)
def test_unapproved_websocket_urls_are_blocked(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_ws_url(url)


def test_worker_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    worker = BybitWebSocketWorker(connector=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    worker.start()
    assert worker.status()["enabled"] is False
    assert worker.status()["worker_running"] is False


def test_successful_ack_is_required_before_ticker_is_usable(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "1")
    connection = _Connection([_ack(), _ticker(), TimeoutError("receive timeout")])
    worker = BybitWebSocketWorker(connector=_connector(connection))

    with pytest.raises(TimeoutError):
        worker.run_cycle()

    status = worker.status()
    assert status["connected"] is False
    assert status["quote_count"] == 1
    assert connection.sent[0]["op"] == "subscribe"
    assert set(connection.sent[0]["args"]) == {"tickers.BTCUSDT", "tickers.ETHUSDT"}
    with pytest.raises(RuntimeError, match="disconnected"):
        worker.quote("BTCUSDT")


def test_negative_or_wrong_ack_blocks_connection(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "1")
    for ack in (
        _ack(success=False, ret_msg="denied"),
        _ack(op="pong"),
        _ack(req_id="unexpected"),
        _ack(data={"failTopics": ["tickers.BTCUSDT"], "successTopics": []}),
    ):
        worker = BybitWebSocketWorker(connector=_connector(_Connection([ack])))
        with pytest.raises(RuntimeError):
            worker.run_cycle()
        assert worker.status()["connected"] is False
        assert worker.status()["quote_count"] == 0


def test_partial_ack_missing_requested_topic_is_blocked(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "1")
    ack = _ack(data={"failTopics": [], "successTopics": ["tickers.BTCUSDT"]})
    worker = BybitWebSocketWorker(connector=_connector(_Connection([ack])))
    with pytest.raises(RuntimeError, match="missing"):
        worker.run_cycle()


def test_spot_subscription_is_limited_to_ten_topics(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_WS_SYMBOLS", ",".join(f"COIN{i}USDT" for i in range(11)))
    with pytest.raises(ValueError, match="at most 10"):
        BybitWebSocketWorker()
