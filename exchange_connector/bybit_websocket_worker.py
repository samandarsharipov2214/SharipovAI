"""Feature-flagged public Bybit ticker worker for the existing Market AI.

The worker only consumes public spot ticker data. It cannot authenticate, access
accounts, or submit orders. A stream becomes usable only after an explicit
successful Bybit subscription acknowledgement.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from config.feature_flags import is_feature_enabled
from .bybit_websocket_state import BybitWebSocketState, ReconnectPolicy

DEFAULT_URL = "wss://stream.bybit.com/v5/public/spot"
OFFICIAL_PUBLIC_STREAM_HOSTS = frozenset(
    {
        "stream.bybit.com",
        "stream.bybit.tr",
        "stream.bybit.id",
        "stream.bybit.kz",
        "stream.bybitgeorgia.ge",
    }
)
_SUBSCRIBE_REQUEST_ID = "sharipovai-public-tickers"


def validate_public_ws_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "wss":
        raise ValueError("Bybit public WebSocket URL must use wss")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Bybit public WebSocket URL must not contain userinfo")
    if parsed.port not in (None, 443):
        raise ValueError("Bybit public WebSocket URL must not use a non-standard port")
    if host not in OFFICIAL_PUBLIC_STREAM_HOSTS:
        raise ValueError("Bybit public WebSocket host is not approved")
    if parsed.path.rstrip("/") != "/v5/public/spot" or parsed.query or parsed.fragment:
        raise ValueError("Bybit public WebSocket URL must target /v5/public/spot")
    return f"wss://{host}/v5/public/spot"


class BybitWebSocketWorker:
    def __init__(
        self,
        *,
        state: BybitWebSocketState | None = None,
        connector: Callable[..., Any] | None = None,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self.state = state or BybitWebSocketState()
        self.url = validate_public_ws_url(os.getenv("BYBIT_WS_PUBLIC_URL", DEFAULT_URL))
        self.symbols = _symbols(os.getenv("BYBIT_WS_SYMBOLS", "BTCUSDT,ETHUSDT"))
        self.receive_timeout = min(
            max(float(os.getenv("BYBIT_WS_RECEIVE_TIMEOUT_SECONDS", "10")), 1.0),
            60.0,
        )
        self._connector = connector
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._thread: threading.Thread | None = None
        self._policy = ReconnectPolicy()

    def enabled(self) -> bool:
        return is_feature_enabled("bybit_websocket")

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="bybit-public-websocket",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self.state.mark_disconnected("worker stopped")

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "url": self.url,
            "symbols": list(self.symbols),
            **self.state.status(),
        }

    def quote(self, symbol: str) -> dict[str, Any]:
        return self.state.current_quote(symbol).to_dict()

    def run_cycle(self) -> None:
        """Run one connection lifecycle; useful for deterministic recovery tests."""
        try:
            with self._connect() as connection:
                self._consume_connection(connection)
        except Exception as exc:
            self.state.mark_disconnected(f"{type(exc).__name__}: {exc}")
            raise

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception:
                if self._wait(self._policy.next_delay()):
                    break

    def _connect(self) -> Any:
        connector = self._connector
        if connector is None:
            from websockets.sync.client import connect

            connector = connect
        return connector(
            self.url,
            open_timeout=10,
            close_timeout=3,
            ping_interval=20,
            ping_timeout=10,
            max_size=1_000_000,
        )

    def _consume_connection(self, connection: Any) -> None:
        topics = tuple(f"tickers.{symbol}" for symbol in self.symbols)
        subscription = {
            "req_id": _SUBSCRIBE_REQUEST_ID,
            "op": "subscribe",
            "args": list(topics),
        }
        connection.send(json.dumps(subscription, separators=(",", ":")))

        raw_ack = connection.recv(timeout=self.receive_timeout)
        ack = _decode_message(raw_ack)
        _validate_subscribe_ack(ack, expected_topics=topics)
        self.state.mark_connected()
        self._policy.reset()

        while not self._stop.is_set():
            raw = connection.recv(timeout=self.receive_timeout)
            payload = _decode_message(raw)
            op = str(payload.get("op", ""))
            if op in {"pong", "ping"} or payload.get("ret_msg") == "pong":
                continue
            if op == "subscribe":
                raise RuntimeError("unexpected duplicate subscription response")
            self.state.ingest_ticker(payload)


def _decode_message(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        raise ValueError("Bybit WebSocket message must be text")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Bybit WebSocket message must be an object")
    return payload


def _validate_subscribe_ack(payload: dict[str, Any], *, expected_topics: tuple[str, ...]) -> None:
    if payload.get("op") != "subscribe" or payload.get("success") is not True:
        raise RuntimeError(f"Bybit subscription rejected: {payload.get('ret_msg') or 'invalid ack'}")
    if payload.get("req_id") not in (None, "", _SUBSCRIBE_REQUEST_ID):
        raise RuntimeError("Bybit subscription ack has unexpected req_id")
    ret_msg = str(payload.get("ret_msg", ""))
    if ret_msg not in {"", "subscribe"}:
        raise RuntimeError(f"Bybit subscription rejected: {ret_msg}")
    data = payload.get("data")
    if isinstance(data, dict):
        failed = tuple(str(item) for item in (data.get("failTopics") or []))
        succeeded = {str(item) for item in (data.get("successTopics") or [])}
        if failed:
            raise RuntimeError(f"Bybit subscription failed for topics: {', '.join(failed)}")
        if succeeded and not set(expected_topics).issubset(succeeded):
            raise RuntimeError("Bybit subscription ack is missing requested topics")


def _symbols(raw: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in raw.split(","):
        symbol = value.strip().upper().replace("/", "").replace("-", "")
        if symbol and symbol.isalnum() and symbol.endswith("USDT") and symbol not in result:
            result.append(symbol)
    if not result:
        raise ValueError("BYBIT_WS_SYMBOLS must contain at least one USDT symbol")
    if len(result) > 10:
        raise ValueError("Bybit Spot allows at most 10 topics in one subscription request")
    return tuple(result)
