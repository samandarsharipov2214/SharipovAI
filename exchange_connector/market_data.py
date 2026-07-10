"""Verified read-only market data for SharipovAI.

Public exchange APIs are used without credentials. The service never invents a
price: it either returns a validated quote with provenance or raises a clear
MarketDataUnavailable error.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


class MarketDataUnavailable(RuntimeError):
    """Raised when no configured provider can return a valid current quote."""


@dataclass(frozen=True, slots=True)
class MarketQuote:
    symbol: str
    price: float
    change_24h_percent: float | None
    volume_24h: float | None
    source: str
    source_url: str
    received_at: str
    received_at_unix_ms: int
    status: str = "live"
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketDataService:
    """Fetch public crypto quotes with provider fallback and strict validation."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 2.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout_seconds = max(float(timeout_seconds), 0.5)
        self.cache_ttl_seconds = max(float(cache_ttl_seconds), 0.0)
        self._client = client
        self._cache: dict[str, tuple[float, MarketQuote]] = {}

    def quote(self, symbol: str) -> MarketQuote:
        clean_symbol = _normalize_symbol(symbol)
        cached = self._cache.get(clean_symbol)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return cached[1]

        errors: list[str] = []
        for provider in (self._fetch_bybit, self._fetch_binance):
            try:
                quote = provider(clean_symbol)
                self._cache[clean_symbol] = (now, quote)
                return quote
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{provider.__name__}: {type(exc).__name__}: {exc}")

        raise MarketDataUnavailable(
            f"Live market data unavailable for {clean_symbol}; no synthetic fallback used. "
            + " | ".join(errors)
        )

    def _fetch_bybit(self, symbol: str) -> MarketQuote:
        url = "https://api.bybit.com/v5/market/tickers"
        response = self._get(url, params={"category": "spot", "symbol": symbol})
        payload = response.json()
        if payload.get("retCode") != 0:
            raise ValueError(payload.get("retMsg") or "Bybit returned an error")
        rows = payload["result"]["list"]
        if not rows:
            raise ValueError("Bybit returned no ticker")
        row = rows[0]
        return _make_quote(
            symbol=symbol,
            price=row.get("lastPrice"),
            change_24h=_fraction_to_percent(row.get("price24hPcnt")),
            volume_24h=row.get("turnover24h"),
            source="bybit",
            source_url=url,
        )

    def _fetch_binance(self, symbol: str) -> MarketQuote:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = self._get(url, params={"symbol": symbol})
        row = response.json()
        return _make_quote(
            symbol=symbol,
            price=row.get("lastPrice"),
            change_24h=row.get("priceChangePercent"),
            volume_24h=row.get("quoteVolume"),
            source="binance",
            source_url=url,
        )

    def _get(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            response = self._client.get(url, params=params, timeout=self.timeout_seconds)
        else:
            response = httpx.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response


def _normalize_symbol(symbol: str) -> str:
    clean = str(symbol).strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("symbol must be a valid exchange ticker such as BTCUSDT")
    return clean


def _positive_float(value: Any, field_name: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return parsed


def _optional_nonnegative_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = float(value)
    if parsed < 0:
        raise ValueError("value must not be negative")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _fraction_to_percent(value: Any) -> float | None:
    parsed = _optional_float(value)
    return None if parsed is None else parsed * 100.0


def _make_quote(
    *,
    symbol: str,
    price: Any,
    change_24h: Any,
    volume_24h: Any,
    source: str,
    source_url: str,
) -> MarketQuote:
    now = datetime.now(UTC)
    return MarketQuote(
        symbol=symbol,
        price=_positive_float(price, "price"),
        change_24h_percent=_optional_float(change_24h),
        volume_24h=_optional_nonnegative_float(volume_24h),
        source=source,
        source_url=source_url,
        received_at=now.isoformat(),
        received_at_unix_ms=int(now.timestamp() * 1000),
    )
