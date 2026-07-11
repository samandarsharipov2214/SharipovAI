"""Fail-closed state and reconnect policy for Bybit public ticker streams.

This module does not open sockets or execute trades. It validates ticker events,
tracks freshness, and calculates bounded reconnect delays so consumers never use
missing, malformed, or stale stream data as if it were current.
"""
from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StreamQuote:
    symbol: str
    price: float
    exchange_timestamp_ms: int
    received_at_ms: int
    sequence: int | None
    source: str = "bybit_websocket_v5"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitWebSocketState:
    """Thread-safe ticker state that fails closed when evidence is stale."""

    def __init__(self) -> None:
        self.max_age_seconds = max(float(os.getenv("BYBIT_WS_MAX_QUOTE_AGE_SECONDS", "1.0")), 0.1)
        self.max_future_skew_ms = max(int(os.getenv("BYBIT_WS_MAX_FUTURE_SKEW_MS", "1000")), 0)
        self.max_exchange_lag_ms = max(int(os.getenv("BYBIT_WS_MAX_EXCHANGE_LAG_MS", "3000")), 100)
        self._quotes: dict[str, StreamQuote] = {}
        self._connected = False
        self._last_error: str | None = None
        self._disconnects = 0
        self._lock = threading.RLock()

    def mark_connected(self) -> None:
        with self._lock:
            self._connected = True
            self._last_error = None

    def mark_disconnected(self, error: Exception | str | None = None) -> None:
        with self._lock:
            self._connected = False
            self._disconnects += 1
            self._last_error = None if error is None else str(error)

    def ingest_ticker(self, payload: dict[str, Any], *, received_at_ms: int | None = None) -> StreamQuote:
        now_ms = int(time.time() * 1000) if received_at_ms is None else int(received_at_ms)
        topic = str(payload.get("topic", ""))
        data = payload.get("data")
        if not topic.startswith("tickers.") or not isinstance(data, dict):
            raise ValueError("payload is not a Bybit ticker event")

        symbol = topic.split(".", 1)[1].strip().upper()
        if not symbol or not symbol.isalnum():
            raise ValueError("ticker symbol is invalid")
        price = _positive_float(data.get("lastPrice"), "lastPrice")
        exchange_ms = int(payload.get("ts") or data.get("ts") or 0)
        if exchange_ms <= 0:
            raise ValueError("ticker exchange timestamp is missing")
        if exchange_ms > now_ms + self.max_future_skew_ms:
            raise ValueError("ticker timestamp is too far in the future")
        if now_ms - exchange_ms > self.max_exchange_lag_ms:
            raise ValueError("ticker event arrived too late")

        sequence_raw = payload.get("cs")
        sequence = int(sequence_raw) if sequence_raw is not None else None
        quote = StreamQuote(
            symbol=symbol,
            price=price,
            exchange_timestamp_ms=exchange_ms,
            received_at_ms=now_ms,
            sequence=sequence,
        )
        with self._lock:
            previous = self._quotes.get(symbol)
            if previous and sequence is not None and previous.sequence is not None and sequence <= previous.sequence:
                raise ValueError("ticker sequence did not advance")
            self._quotes[symbol] = quote
        return quote

    def current_quote(self, symbol: str, *, now_ms: int | None = None) -> StreamQuote:
        clean = str(symbol).strip().upper().replace("/", "").replace("-", "")
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            quote = self._quotes.get(clean)
            connected = self._connected
        if not connected:
            raise RuntimeError("Bybit WebSocket is disconnected")
        if quote is None:
            raise RuntimeError(f"Bybit WebSocket quote is unavailable for {clean}")
        age_seconds = max((current_ms - quote.received_at_ms) / 1000, 0.0)
        if age_seconds > self.max_age_seconds:
            raise RuntimeError(f"Bybit WebSocket quote is stale: {age_seconds:.3f}s")
        return quote

    def status(self, *, now_ms: int | None = None) -> dict[str, Any]:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            quotes = dict(self._quotes)
            connected = self._connected
            error = self._last_error
            disconnects = self._disconnects
        ages = {
            symbol: round(max((current_ms - quote.received_at_ms) / 1000, 0.0), 6)
            for symbol, quote in quotes.items()
        }
        return {
            "connected": connected,
            "verified": connected and bool(quotes) and all(age <= self.max_age_seconds for age in ages.values()),
            "quote_count": len(quotes),
            "quote_ages_seconds": ages,
            "disconnect_count": disconnects,
            "last_error": error,
        }


class ReconnectPolicy:
    """Bounded exponential reconnect delay with jitter and reset support."""

    def __init__(self) -> None:
        self.base_seconds = max(float(os.getenv("BYBIT_WS_RECONNECT_BASE_SECONDS", "0.5")), 0.1)
        self.max_seconds = max(float(os.getenv("BYBIT_WS_RECONNECT_MAX_SECONDS", "15")), self.base_seconds)
        self._attempt = 0

    def next_delay(self, *, random_value: float | None = None) -> float:
        jitter = random.random() if random_value is None else min(max(float(random_value), 0.0), 1.0)
        raw = self.base_seconds * (2 ** self._attempt)
        self._attempt += 1
        return min(raw + raw * 0.2 * jitter, self.max_seconds)

    def reset(self) -> None:
        self._attempt = 0


def _positive_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed
