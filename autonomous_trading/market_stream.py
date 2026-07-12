"""Compatibility market stream backed by a Bybit public WebSocket worker.

Production uses :class:`SharedVerifiedMarketStream`, which also requires REST and
multi-exchange evidence. This class remains for diagnostics and compatibility but
no longer opens an independent socket implementation.
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
    """Backward-compatible adapter that reuses one worker instance."""

    def __init__(
        self,
        symbols: list[str] | tuple[str, ...] | None = None,
        *,
        worker: Any | None = None,
    ) -> None:
        self.worker = worker or BybitWebSocketWorker()
        configured = tuple(symbols or getattr(self.worker, "symbols", ()))
        self.symbols = tuple(_symbol(item) for item in configured)
        if not self.symbols:
            raise ValueError("market stream requires at least one configured symbol")
        self.shared_worker = worker is not None

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    def quote(self, symbol: str) -> StreamQuote:
        clean = _symbol(symbol)
        raw = self.worker.quote(clean)
        if not isinstance(raw, dict):
            to_dict = getattr(raw, "to_dict", None)
            if not callable(to_dict):
                raise RuntimeError("worker quote has an invalid structure")
            raw = to_dict()
        if raw.get("verified") is False:
            raise RuntimeError(f"worker quote is not verified for {clean}")
        received_at_ms = _positive_int(raw.get("received_at_ms"), "received_at_ms")
        return StreamQuote(
            symbol=clean,
            price=_positive_float(raw.get("price"), "price"),
            change_24h_percent=_optional_float(raw.get("change_24h_percent")),
            volume_24h=_optional_nonnegative(raw.get("volume_24h")),
            source=str(raw.get("source") or "bybit_websocket_v5"),
            received_at=datetime.fromtimestamp(received_at_ms / 1000, UTC).isoformat(),
            received_at_unix_ms=received_at_ms,
            verified=True,
        )

    def snapshot(self) -> dict[str, Any]:
        status = self.worker.status()
        quotes: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        raw_ages: list[float] = []
        for symbol in self.symbols:
            try:
                raw = self.worker.quote(symbol)
                if not isinstance(raw, dict):
                    raw = raw.to_dict()
                quote = self.quote(symbol)
                quotes[symbol] = quote.to_dict()
                age = raw.get("age_seconds")
                if age is not None and math.isfinite(float(age)):
                    raw_ages.append(max(float(age), 0.0))
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        status_ages = status.get("quote_ages_seconds") if isinstance(status, dict) else None
        if isinstance(status_ages, dict):
            for value in status_ages.values():
                try:
                    parsed = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(parsed):
                    raw_ages.append(max(parsed, 0.0))
        verified = bool(status.get("verified")) and len(quotes) == len(self.symbols) and not errors
        return {
            "status": "live" if verified else "stale",
            "connected": bool(status.get("connected")),
            "verified": verified,
            "source": "shared_bybit_websocket",
            "age_seconds": max(raw_ages) if raw_ages else None,
            "symbols": list(self.symbols),
            "quotes": quotes,
            "quote_errors": errors,
            "last_error": str(status.get("last_error") or ""),
            "synthetic_fallback_used": False,
            "shared_worker": True,
        }


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("invalid market symbol")
    return clean


def _positive_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be positive")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be positive")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("optional value must be finite")
    return parsed


def _optional_nonnegative(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is not None and parsed < 0:
        raise ValueError("optional value must be non-negative")
    return parsed


__all__ = ["MarketStream", "StreamQuote"]
