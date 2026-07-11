"""Feature-flagged public Bybit ticker worker for the existing Market AI.

The worker only consumes public spot ticker data. It cannot authenticate, access
accounts, or submit orders. Validated events are delegated to
``BybitWebSocketState`` so disconnected, malformed, or stale data remains
unusable.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from typing import Any

from config.feature_flags import is_feature_enabled
from .bybit_websocket_state import BybitWebSocketState, ReconnectPolicy


DEFAULT_URL = "wss://stream.bybit.com/v5/public/spot"


class BybitWebSocketWorker:
    def __init__(
        self,
        *,
        state: BybitWebSocketState | None = None,
        connector: Callable[..., Any] | None = None,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self.state = state or BybitWebSocketState()
        self.url = os.getenv("BYBIT_WS_PUBLIC_URL", DEFAULT_URL).strip() or DEFAULT_URL
        self.symbols = _symbols(os.getenv("BYBIT_WS_SYMBOLS", "BTCUSDT,ETHUSDT"))
        self.receive_timeout = max(float(os.getenv("BYBIT_WS_RECEIVE_TIMEOUT_SECONDS", "10")), 1.0)
        self._connector = connector
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._thread: threading.Thread | None = None
        self._policy = ReconnectPolicy()

    def enabled(self) -> bool:
        return is_feature_enabled("bybit_websocket")

    def start(self) -> None:
        if not self.enabled() or self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bybit-public-websocket", daemon=True)
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

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._connect() as connection:
                    self._consume_connection(connection)
            except Exception as exc:
                self.state.mark_disconnected(f"{type(exc).__name__}: {exc}")
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
        subscription = {"op": "subscribe", "args": [f"tickers.{symbol}" for symbol in self.symbols]}
        connection.send(json.dumps(subscription))
        self.state.mark_connected()
        self._policy.reset()
        while not self._stop.is_set():
            raw = connection.recv(timeout=self.receive_timeout)
            payload = json.loads(raw)
            if payload.get("op") in {"subscribe", "pong"} or payload.get("success") is True:
                continue
            self.state.ingest_ticker(payload)


def _symbols(raw: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in raw.split(","):
        symbol = value.strip().upper().replace("/", "").replace("-", "")
        if symbol and symbol.isalnum() and symbol.endswith("USDT") and symbol not in result:
            result.append(symbol)
    if not result:
        raise ValueError("BYBIT_WS_SYMBOLS must contain at least one USDT symbol")
    return tuple(result)
