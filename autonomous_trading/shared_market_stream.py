"""Shared verified market stream for the canonical paper runtime.

The adapter reuses the dashboard's existing Bybit public WebSocket worker and
read-only market services.  It never opens a second socket and never fabricates a
quote.  A trading quote is usable only when WebSocket freshness, REST metadata,
and multi-exchange price agreement all succeed.
"""
from __future__ import annotations

import math
import os
import threading
from datetime import UTC, datetime
from typing import Any

from exchange_connector.market_data import MarketDataService
from exchange_connector.multi_exchange_consensus import MultiExchangeConsensus
from storage import ProjectDatabase, ProjectDomainStore

from .market_stream import StreamQuote


class SharedVerifiedMarketStream:
    """Compatibility stream backed by the already-running canonical market worker."""

    def __init__(
        self,
        worker: Any,
        market_data: MarketDataService,
        consensus: MultiExchangeConsensus,
        *,
        database: ProjectDatabase,
        symbols: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.worker = worker
        self.market_data = market_data
        self.consensus = consensus
        self.database = database
        self.database.initialize()
        self.store = ProjectDomainStore(database)
        configured = tuple(symbols or getattr(worker, "symbols", ()))
        self.symbols = tuple(_symbol(item) for item in configured)
        if not self.symbols:
            raise ValueError("shared market stream requires at least one symbol")
        self.max_ws_consensus_deviation_percent = min(
            max(float(os.getenv("PAPER_MAX_WS_CONSENSUS_DEVIATION_PERCENT", "0.75")), 0.05),
            3.0,
        )
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[int, StreamQuote, dict[str, Any]]] = {}

    def start(self) -> None:
        """Start the shared worker idempotently; ownership remains with market-data API."""

        self.worker.start()

    def stop(self) -> None:
        """Do not stop a worker shared with Market Intelligence and the dashboard."""

        return None

    def quote(self, symbol: str) -> StreamQuote:
        clean = _symbol(symbol)
        if clean not in self.symbols:
            raise RuntimeError(f"symbol is not configured in shared stream: {clean}")
        websocket = self.worker.quote(clean)
        received_at_ms = _positive_int(websocket.get("received_at_ms"), "received_at_ms")
        with self._lock:
            cached = self._cache.get(clean)
            if cached is not None and cached[0] == received_at_ms:
                return cached[1]

        ws_price = _positive_float(websocket.get("price"), "websocket price")
        rest = self.market_data.quote(clean)
        if rest.verified is not True:
            raise RuntimeError("REST market quote is not verified")
        cross = self.consensus.quote(clean)
        if cross.verified is not True or cross.source_count < 3:
            raise RuntimeError("multi-exchange consensus is not verified")
        deviation = abs(ws_price - cross.price) / cross.price * 100.0
        if not math.isfinite(deviation) or deviation > self.max_ws_consensus_deviation_percent:
            raise RuntimeError(
                f"Bybit WebSocket price deviates from multi-exchange consensus by {deviation:.6f}%"
            )

        now = datetime.now(UTC)
        quote = StreamQuote(
            symbol=clean,
            price=ws_price,
            change_24h_percent=rest.change_24h_percent,
            volume_24h=rest.volume_24h,
            source="bybit_websocket_v5+multi_exchange_consensus",
            received_at=now.isoformat(),
            received_at_unix_ms=received_at_ms,
            verified=True,
        )
        evidence = {
            "verified": True,
            "symbol": clean,
            "websocket_source": str(websocket.get("source") or "bybit_websocket_v5"),
            "websocket_price": ws_price,
            "websocket_exchange_timestamp_ms": _positive_int(
                websocket.get("exchange_timestamp_ms"), "exchange_timestamp_ms"
            ),
            "websocket_received_at_ms": received_at_ms,
            "rest_source": rest.source,
            "rest_received_at_ms": rest.received_at_unix_ms,
            "change_24h_percent": rest.change_24h_percent,
            "volume_24h": rest.volume_24h,
            "consensus_price": cross.price,
            "consensus_sources": list(cross.sources),
            "consensus_source_count": cross.source_count,
            "consensus_maximum_deviation_percent": cross.maximum_deviation_percent,
            "ws_consensus_deviation_percent": round(deviation, 8),
            "synthetic_fallback_used": False,
            "database_backed": True,
            "shared_worker": True,
        }
        self.store.save_market_quote(
            {
                "provider": "bybit_websocket_v5",
                "symbol": clean,
                "category": "spot",
                "price": ws_price,
                "exchange_timestamp_ms": evidence["websocket_exchange_timestamp_ms"],
                "received_at_unix_ms": received_at_ms,
                "verified": True,
                "consensus_sources": list(cross.sources),
            }
        )
        with self._lock:
            self._cache[clean] = (received_at_ms, quote, evidence)
        return quote

    def evidence(self, symbol: str) -> dict[str, Any]:
        clean = _symbol(symbol)
        quote = self.quote(clean)
        with self._lock:
            cached = self._cache.get(clean)
            if cached is None or cached[1].received_at_unix_ms != quote.received_at_unix_ms:
                raise RuntimeError("market evidence cache is unavailable")
            return dict(cached[2])

    def snapshot(self) -> dict[str, Any]:
        status = self.worker.status()
        quotes: dict[str, dict[str, Any]] = {}
        failures: dict[str, str] = {}
        for symbol in self.symbols:
            try:
                raw = self.worker.quote(symbol)
                quotes[symbol] = {
                    "symbol": symbol,
                    "price": _positive_float(raw.get("price"), "price"),
                    "received_at_unix_ms": _positive_int(raw.get("received_at_ms"), "received_at_ms"),
                    "source": str(raw.get("source") or "bybit_websocket_v5"),
                    "verified": True,
                }
            except Exception as exc:
                failures[symbol] = f"{type(exc).__name__}: {exc}"
        ages = status.get("quote_ages_seconds") if isinstance(status, dict) else {}
        finite_ages = [float(value) for value in (ages or {}).values() if _is_finite(value)]
        age = max(finite_ages) if finite_ages else None
        verified = bool(status.get("verified")) and len(quotes) == len(self.symbols) and not failures
        return {
            "status": "live" if verified else "stale",
            "connected": bool(status.get("connected")),
            "verified": verified,
            "source": "shared_bybit_websocket_v5",
            "age_seconds": age,
            "symbols": list(self.symbols),
            "quotes": quotes,
            "last_error": str(status.get("last_error") or "") if not failures else str(failures),
            "synthetic_fallback_used": False,
            "database_backed": True,
            "shared_worker": True,
            "owns_socket": False,
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


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


__all__ = ["SharedVerifiedMarketStream"]
