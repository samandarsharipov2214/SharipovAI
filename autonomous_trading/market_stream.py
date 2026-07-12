"""Compatibility adapter over the one canonical public Bybit WebSocket worker.

The paper runtime must never open a second socket. This adapter preserves the old
MarketStream API while delegating lifecycle and quote access to the shared worker.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker


@dataclass(frozen=True, slots=True)
class StreamQuote:
    symbol: str
    price: float
    change_24h_percent: float | None
    volume_24h: float | None
    source: str
    received_at: str
    received_at_unix_ms: int
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketStream:
    """Read-only adapter; all network I/O belongs to ``BybitWebSocketWorker``."""

    def __init__(
        self,
        symbols: list[str] | tuple[str, ...] | None = None,
        *,
        worker: BybitWebSocketWorker | Any | None = None,
    ) -> None:
        self.worker = worker or BybitWebSocketWorker()
        inherited = tuple(str(item).strip().upper() for item in getattr(self.worker, "symbols", ()) if str(item).strip())
        requested = tuple(str(item).strip().upper() for item in (symbols or inherited) if str(item).strip())
        self.symbols = list(dict.fromkeys(requested or inherited))
        if not self.symbols:
            raise ValueError("MarketStream requires at least one configured symbol")

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    def quote(self, symbol: str) -> StreamQuote:
        clean = _symbol(symbol)
        payload = self.worker.quote(clean)
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("canonical market worker returned an invalid quote")
        if payload.get("verified") is not True:
            raise RuntimeError(f"Market quote for {clean} is not verified")
        payload_symbol = _symbol(payload.get("symbol", clean))
        if payload_symbol != clean:
            raise RuntimeError("market quote symbol mismatch")
        price = _positive(payload.get("price"), "price")
        change = _optional_finite(payload.get("change_24h_percent"), "change_24h_percent")
        volume = _optional_nonnegative(
            payload.get("turnover_24h", payload.get("volume_24h")),
            "volume_24h",
        )
        received_ms = _positive_int(
            payload.get("received_at_ms", payload.get("received_at_unix_ms")),
            "received_at_ms",
        )
        source = str(payload.get("source") or "bybit_public_websocket")
        received_at = str(payload.get("received_at") or datetime.fromtimestamp(received_ms / 1000, UTC).isoformat())
        return StreamQuote(
            symbol=clean,
            price=price,
            change_24h_percent=change,
            volume_24h=volume,
            source=source,
            received_at=received_at,
            received_at_unix_ms=received_ms,
            verified=True,
        )

    def snapshot(self) -> dict[str, Any]:
        raw_status = self.worker.status()
        status = raw_status if isinstance(raw_status, dict) else {}
        quotes: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        newest_ms = 0
        for symbol in self.symbols:
            try:
                quote = self.quote(symbol)
                quotes[symbol] = quote.to_dict()
                newest_ms = max(newest_ms, quote.received_at_unix_ms)
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        connected = status.get("connected") is True
        worker_verified = status.get("verified") is True
        verified = connected and worker_verified and len(quotes) == len(self.symbols) and not errors
        age_seconds = None
        if newest_ms:
            import time

            age_seconds = max(0.0, time.time() - newest_ms / 1000)
        return {
            "status": "live" if verified else "stale",
            "connected": connected,
            "verified": verified,
            "source": "bybit_public_websocket",
            "age_seconds": age_seconds,
            "symbols": list(self.symbols),
            "quotes": quotes,
            "quote_errors": errors,
            "last_error": str(status.get("last_error") or ""),
            "synthetic_fallback_used": False,
            "shared_worker": True,
            "database_backed": status.get("database_backed") is True,
        }


def _symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not text or not text.isalnum():
        raise ValueError("symbol is invalid")
    return text


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} is invalid")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _optional_finite(value: Any, name: str) -> float | None:
    return None if value in (None, "") else _finite(value, name)


def _optional_nonnegative(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    parsed = _finite(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} is invalid")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed
