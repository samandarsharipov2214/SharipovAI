"""Fail-closed state and reconnect policy for Bybit public ticker streams.

The state validates ticker events, tracks connection/freshness evidence and
stores the latest verified quote in the canonical ProjectDatabase when supplied.
It never opens sockets and never executes trades.
"""
from __future__ import annotations

import math
import os
import random
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from storage import ProjectDatabase


@dataclass(frozen=True, slots=True)
class StreamQuote:
    symbol: str
    price: float
    exchange_timestamp_ms: int
    received_at_ms: int
    sequence: int | None
    change_24h_percent: float | None = None
    source: str = "bybit_websocket_v5"
    verified: bool = True
    database_backed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


class BybitWebSocketState:
    """Thread-safe ticker state that fails closed when evidence is stale."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        max_age_seconds: float | None = None,
    ) -> None:
        configured_age = (
            float(max_age_seconds)
            if max_age_seconds is not None
            else float(os.getenv("BYBIT_WS_MAX_QUOTE_AGE_SECONDS", "1.0"))
        )
        self.max_age_seconds = min(max(configured_age, 0.1), 30.0)
        self.max_future_skew_ms = min(
            max(int(os.getenv("BYBIT_WS_MAX_FUTURE_SKEW_MS", "1000")), 0),
            10_000,
        )
        self.max_exchange_lag_ms = min(
            max(int(os.getenv("BYBIT_WS_MAX_EXCHANGE_LAG_MS", "3000")), 100),
            60_000,
        )
        self.database = database
        if self.database is not None:
            self.database.initialize()
        self._quotes: dict[str, StreamQuote] = {}
        self._connected = False
        self._last_error: str | None = None
        self._disconnects = 0
        self._connected_at_ms = 0
        self._disconnected_at_ms = 0
        self._lock = threading.RLock()

    def mark_connected(self, *, connected_at_ms: int | None = None) -> None:
        """Mark usable only after a successful Bybit subscription acknowledgement."""
        timestamp = int(time.time() * 1000) if connected_at_ms is None else _positive_int(
            connected_at_ms, "connected_at_ms"
        )
        with self._lock:
            self._connected = True
            self._connected_at_ms = timestamp
            self._last_error = None

    def mark_disconnected(
        self,
        error: Exception | str | None = None,
        *,
        disconnected_at_ms: int | None = None,
    ) -> None:
        timestamp = int(time.time() * 1000) if disconnected_at_ms is None else _positive_int(
            disconnected_at_ms, "disconnected_at_ms"
        )
        with self._lock:
            self._connected = False
            self._disconnected_at_ms = timestamp
            self._disconnects += 1
            self._last_error = None if error is None else str(error)

    def ingest_ticker(
        self,
        payload: dict[str, Any],
        *,
        received_at_ms: int | None = None,
    ) -> StreamQuote:
        now_ms = int(time.time() * 1000) if received_at_ms is None else _positive_int(
            received_at_ms, "received_at_ms"
        )
        wall_clock_ms = int(time.time() * 1000)
        if received_at_ms is not None and now_ms > wall_clock_ms + self.max_future_skew_ms:
            raise ValueError("received_at_ms is too far in the future")

        topic = str(payload.get("topic", "")).strip()
        data = payload.get("data")
        if not topic.startswith("tickers.") or not isinstance(data, dict):
            raise ValueError("payload is not a Bybit ticker event")

        symbol = _symbol(topic.split(".", 1)[1])
        data_symbol = str(data.get("symbol", "")).strip()
        if data_symbol and _symbol(data_symbol) != symbol:
            raise ValueError("ticker data symbol does not match topic")

        price = _positive_float(data.get("lastPrice"), "lastPrice")
        exchange_ms = _positive_int(payload.get("ts") or data.get("ts"), "ticker timestamp")
        if exchange_ms > now_ms + self.max_future_skew_ms:
            raise ValueError("ticker timestamp is too far in the future")
        if now_ms - exchange_ms > self.max_exchange_lag_ms:
            raise ValueError("ticker event arrived too late")

        sequence_raw = payload.get("cs")
        sequence = None if sequence_raw is None else _positive_int(sequence_raw, "cs")
        change = _fraction_to_percent(data.get("price24hPcnt"))
        quote = StreamQuote(
            symbol=symbol,
            price=price,
            exchange_timestamp_ms=exchange_ms,
            received_at_ms=now_ms,
            sequence=sequence,
            change_24h_percent=change,
            database_backed=self.database is not None,
        )
        with self._lock:
            previous = self._quotes.get(symbol)
            if (
                previous
                and sequence is not None
                and previous.sequence is not None
                and sequence <= previous.sequence
            ):
                raise ValueError("ticker sequence did not advance")
            self._quotes[symbol] = quote
        self._persist(quote)
        return quote

    def current_quote(self, symbol: str, *, now_ms: int | None = None) -> StreamQuote:
        clean = _symbol(symbol)
        current_ms = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        with self._lock:
            quote = self._quotes.get(clean)
            connected = self._connected
        if not connected:
            raise RuntimeError("Bybit WebSocket is disconnected or not subscribed")
        if quote is None:
            raise RuntimeError(f"Bybit WebSocket quote is unavailable for {clean}")
        age_ms = current_ms - quote.received_at_ms
        if age_ms < -self.max_future_skew_ms:
            raise RuntimeError("Bybit WebSocket quote receipt time is in the future")
        age_seconds = max(age_ms / 1000, 0.0)
        if age_seconds > self.max_age_seconds:
            raise RuntimeError(f"Bybit WebSocket quote is stale: {age_seconds:.3f}s")
        return quote

    def status(self, *, now_ms: int | None = None) -> dict[str, Any]:
        current_ms = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        with self._lock:
            quotes = dict(self._quotes)
            connected = self._connected
            error = self._last_error
            disconnects = self._disconnects
            connected_at_ms = self._connected_at_ms
            disconnected_at_ms = self._disconnected_at_ms
        ages = {
            symbol: round((current_ms - quote.received_at_ms) / 1000, 6)
            for symbol, quote in quotes.items()
        }
        verified_ages = bool(ages) and all(
            0 <= age <= self.max_age_seconds for age in ages.values()
        )
        return {
            "connected": connected,
            "verified": connected and verified_ages,
            "quote_count": len(quotes),
            "quote_ages_seconds": ages,
            "disconnect_count": disconnects,
            "connected_at_ms": connected_at_ms,
            "disconnected_at_ms": disconnected_at_ms,
            "last_error": error,
            "database_backed": self.database is not None,
            "synthetic_fallback_used": False,
        }

    def _persist(self, quote: StreamQuote) -> None:
        if self.database is None:
            return
        self.database.put_json(
            "market_quotes",
            quote.symbol,
            {
                **quote.to_dict(),
                "provider": quote.source,
                "category": "spot",
                "synthetic_fallback_used": False,
            },
        )


class ReconnectPolicy:
    """Bounded exponential reconnect delay with jitter and reset support."""

    def __init__(self) -> None:
        self.base_seconds = min(
            max(float(os.getenv("BYBIT_WS_RECONNECT_BASE_SECONDS", "0.5")), 0.1),
            5.0,
        )
        self.max_seconds = min(
            max(float(os.getenv("BYBIT_WS_RECONNECT_MAX_SECONDS", "15")), self.base_seconds),
            60.0,
        )
        self._attempt = 0

    def next_delay(self, *, random_value: float | None = None) -> float:
        jitter = random.random() if random_value is None else min(max(float(random_value), 0.0), 1.0)
        raw = self.base_seconds * (2**self._attempt)
        self._attempt += 1
        return min(raw + raw * 0.2 * jitter, self.max_seconds)

    def reset(self) -> None:
        self._attempt = 0


def _fraction_to_percent(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("price24hPcnt must be finite")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("price24hPcnt must be finite")
    return parsed * 100.0


def _positive_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} is invalid")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} is invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _symbol(value: Any) -> str:
    text = str(value).strip().upper().replace("/", "").replace("-", "")
    if not text or len(text) > 30 or not text.isalnum():
        raise ValueError("ticker symbol is invalid")
    return text
