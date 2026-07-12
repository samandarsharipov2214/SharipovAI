"""Fail-closed state and reconnect policy for Bybit public ticker streams.

This module never opens sockets or executes trades. It validates ticker events,
tracks connection/freshness evidence and persists verified quotes in the canonical
ProjectDatabase when one is supplied.
"""
from __future__ import annotations

import math
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, replace
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
    turnover_24h: float | None = None
    source: str = "bybit_public_websocket"
    verified: bool = True
    database_backed: bool = False
    age_seconds: float = 0.0

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
            float(os.getenv("BYBIT_WS_MAX_QUOTE_AGE_SECONDS", "1.0"))
            if max_age_seconds is None
            else float(max_age_seconds)
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
        self._restore_status()

    def mark_connected(self, *, connected_at_ms: int | None = None) -> None:
        """Mark usable only after a successful Bybit subscription acknowledgement."""

        timestamp = _timestamp(connected_at_ms)
        with self._lock:
            self._connected = True
            self._last_error = None
            self._connected_at_ms = timestamp
        self._persist_status()

    def mark_disconnected(
        self,
        error: Exception | str | None = None,
        *,
        disconnected_at_ms: int | None = None,
    ) -> None:
        timestamp = _timestamp(disconnected_at_ms)
        with self._lock:
            self._connected = False
            self._disconnects += 1
            self._last_error = None if error is None else str(error)
            self._disconnected_at_ms = timestamp
        self._persist_status()

    def ingest_ticker(
        self,
        payload: dict[str, Any],
        *,
        received_at_ms: int | None = None,
    ) -> StreamQuote:
        now_ms = _timestamp(received_at_ms)
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
        change_raw = data.get("price24hPcnt")
        change = None if change_raw in (None, "") else _finite_float(change_raw, "price24hPcnt") * 100.0
        turnover_raw = data.get("turnover24h")
        turnover = None if turnover_raw in (None, "") else _non_negative_float(turnover_raw, "turnover24h")
        quote = StreamQuote(
            symbol=symbol,
            price=price,
            exchange_timestamp_ms=exchange_ms,
            received_at_ms=now_ms,
            sequence=sequence,
            change_24h_percent=change,
            turnover_24h=turnover,
            database_backed=self.database is not None,
        )
        with self._lock:
            previous = self._quotes.get(symbol)
            if previous and sequence is not None and previous.sequence is not None and sequence <= previous.sequence:
                raise ValueError("ticker sequence did not advance")
            if previous and exchange_ms < previous.exchange_timestamp_ms:
                raise ValueError("ticker timestamp moved backwards")
            self._quotes[symbol] = quote
        self._persist_quote(quote)
        return quote

    def current_quote(self, symbol: str, *, now_ms: int | None = None) -> StreamQuote:
        clean = _symbol(symbol)
        current_ms = _timestamp(now_ms)
        with self._lock:
            quote = self._quotes.get(clean)
            connected = self._connected
        if quote is None:
            quote = self._restore_quote(clean)
            if quote is not None:
                with self._lock:
                    self._quotes[clean] = quote
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
        return replace(
            quote,
            verified=True,
            database_backed=self.database is not None,
            age_seconds=age_seconds,
        )

    def status(self, *, now_ms: int | None = None) -> dict[str, Any]:
        current_ms = _timestamp(now_ms)
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
        verified_ages = bool(ages) and all(0 <= age <= self.max_age_seconds for age in ages.values())
        return {
            "connected": connected,
            "verified": connected and verified_ages,
            "quote_count": len(quotes),
            "quote_ages_seconds": ages,
            "disconnect_count": disconnects,
            "last_error": error,
            "connected_at_ms": connected_at_ms,
            "disconnected_at_ms": disconnected_at_ms,
            "database_backed": self.database is not None,
        }

    def _persist_quote(self, quote: StreamQuote) -> None:
        if self.database is None:
            return
        self.database.put_json("market_quotes", quote.symbol, quote.to_dict())

    def _restore_quote(self, symbol: str) -> StreamQuote | None:
        if self.database is None:
            return None
        stored = self.database.get_json("market_quotes", symbol)
        value = stored.get("value") if stored else None
        if not isinstance(value, dict):
            return None
        try:
            return StreamQuote(
                symbol=_symbol(value.get("symbol")),
                price=_positive_float(value.get("price"), "price"),
                exchange_timestamp_ms=_positive_int(value.get("exchange_timestamp_ms"), "exchange_timestamp_ms"),
                received_at_ms=_positive_int(value.get("received_at_ms"), "received_at_ms"),
                sequence=None if value.get("sequence") is None else _positive_int(value.get("sequence"), "sequence"),
                change_24h_percent=None if value.get("change_24h_percent") is None else _finite_float(value.get("change_24h_percent"), "change_24h_percent"),
                turnover_24h=None if value.get("turnover_24h") is None else _non_negative_float(value.get("turnover_24h"), "turnover_24h"),
                source=str(value.get("source") or "bybit_public_websocket"),
                database_backed=True,
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"persisted market quote is invalid: {symbol}") from exc

    def _persist_status(self) -> None:
        if self.database is None:
            return
        with self._lock:
            payload = {
                "connected": self._connected,
                "last_error": self._last_error,
                "disconnect_count": self._disconnects,
                "connected_at_ms": self._connected_at_ms,
                "disconnected_at_ms": self._disconnected_at_ms,
            }
        self.database.put_json("market_stream", "bybit_public", payload)

    def _restore_status(self) -> None:
        if self.database is None:
            return
        stored = self.database.get_json("market_stream", "bybit_public")
        value = stored.get("value") if stored else None
        if not isinstance(value, dict):
            return
        with self._lock:
            # A restarted process must re-authenticate the subscription; never restore connected=True.
            self._connected = False
            self._last_error = "restart requires a fresh subscription acknowledgement"
            self._disconnects = max(int(value.get("disconnect_count", 0)), 0)
            self._connected_at_ms = max(int(value.get("connected_at_ms", 0)), 0)
            self._disconnected_at_ms = max(int(value.get("disconnected_at_ms", 0)), 0)


class ReconnectPolicy:
    """Bounded exponential reconnect delay with jitter and reset support."""

    def __init__(self) -> None:
        self.base_seconds = min(max(float(os.getenv("BYBIT_WS_RECONNECT_BASE_SECONDS", "0.5")), 0.1), 5.0)
        self.max_seconds = min(max(float(os.getenv("BYBIT_WS_RECONNECT_MAX_SECONDS", "15")), self.base_seconds), 60.0)
        self._attempt = 0

    def next_delay(self, *, random_value: float | None = None) -> float:
        jitter = random.random() if random_value is None else min(max(float(random_value), 0.0), 1.0)
        raw = self.base_seconds * (2**self._attempt)
        self._attempt += 1
        return min(raw + raw * 0.2 * jitter, self.max_seconds)

    def reset(self) -> None:
        self._attempt = 0


def _timestamp(value: Any | None) -> int:
    if value is None:
        return int(time.time() * 1000)
    return _positive_int(value, "timestamp")


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} is invalid")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _positive_float(value: Any, field: str) -> float:
    parsed = _finite_float(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return parsed


def _non_negative_float(value: Any, field: str) -> float:
    parsed = _finite_float(value, field)
    if parsed < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
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
