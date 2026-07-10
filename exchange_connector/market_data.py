"""Verified read-only multi-exchange market data for SharipovAI.

Five public spot exchanges are queried independently: Bybit, Binance, OKX,
Kraken and Coinbase. No synthetic price is ever created. Consumers that need
strong evidence should call ``consensus_quote``; the legacy ``quote`` method
keeps ordered fallback compatibility.
"""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

import httpx


class MarketDataUnavailable(RuntimeError):
    """Raised when providers cannot return enough valid current quotes."""


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
    constituents: tuple[dict[str, Any], ...] = ()
    deviation_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketDataService:
    """Fetch public crypto quotes with five-provider consensus and validation."""

    PROVIDER_NAMES = ("bybit", "binance", "okx", "kraken", "coinbase")

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 2.0,
        client: httpx.Client | None = None,
        minimum_consensus_sources: int = 3,
        maximum_deviation_percent: float = 0.75,
    ) -> None:
        self.timeout_seconds = max(float(timeout_seconds), 0.5)
        self.cache_ttl_seconds = max(float(cache_ttl_seconds), 0.0)
        self.minimum_consensus_sources = min(max(int(minimum_consensus_sources), 2), len(self.PROVIDER_NAMES))
        self.maximum_deviation_percent = max(float(maximum_deviation_percent), 0.05)
        self._client = client
        self._cache: dict[str, tuple[float, MarketQuote]] = {}
        self._consensus_cache: dict[str, tuple[float, MarketQuote]] = {}

    def quote(self, symbol: str) -> MarketQuote:
        """Return the first valid provider quote for backward-compatible callers."""
        clean_symbol = _normalize_symbol(symbol)
        cached = self._cache.get(clean_symbol)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return cached[1]
        errors: list[str] = []
        for name, provider in self._providers():
            try:
                quote = provider(clean_symbol)
                self._cache[clean_symbol] = (now, quote)
                return quote
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        raise MarketDataUnavailable(
            f"Live market data unavailable for {clean_symbol}; no synthetic fallback used. " + " | ".join(errors)
        )

    def all_quotes(self, symbol: str) -> dict[str, Any]:
        """Query all five exchanges independently and return per-provider health."""
        clean_symbol = _normalize_symbol(symbol)
        quotes: list[MarketQuote] = []
        errors: dict[str, str] = {}
        providers = self._providers()
        with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="exchange-quote") as executor:
            futures = {executor.submit(provider, clean_symbol): name for name, provider in providers}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    quote = future.result()
                    if quote.verified and quote.price > 0:
                        quotes.append(quote)
                    else:
                        errors[name] = "unverified or non-positive quote"
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                    errors[name] = f"{type(exc).__name__}: {exc}"
        quotes.sort(key=lambda item: item.source)
        return {
            "symbol": clean_symbol,
            "configured_sources": list(self.PROVIDER_NAMES),
            "online_count": len(quotes),
            "offline_count": len(self.PROVIDER_NAMES) - len(quotes),
            "quotes": quotes,
            "errors": errors,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def consensus_quote(self, symbol: str) -> MarketQuote:
        """Return the median of mutually consistent quotes from at least 3 exchanges."""
        clean_symbol = _normalize_symbol(symbol)
        cached = self._consensus_cache.get(clean_symbol)
        now_mono = time.monotonic()
        if cached and now_mono - cached[0] <= self.cache_ttl_seconds:
            return cached[1]
        snapshot = self.all_quotes(clean_symbol)
        quotes: list[MarketQuote] = snapshot["quotes"]
        if len(quotes) < self.minimum_consensus_sources:
            raise MarketDataUnavailable(
                f"Consensus unavailable for {clean_symbol}: {len(quotes)}/{len(self.PROVIDER_NAMES)} exchanges online; "
                f"minimum {self.minimum_consensus_sources}. Errors: {snapshot['errors']}"
            )
        raw_median = statistics.median(item.price for item in quotes)
        accepted = [
            item for item in quotes
            if abs(item.price - raw_median) / raw_median * 100 <= self.maximum_deviation_percent
        ]
        rejected = [item.source for item in quotes if item not in accepted]
        if len(accepted) < self.minimum_consensus_sources:
            raise MarketDataUnavailable(
                f"Price disagreement for {clean_symbol}: only {len(accepted)} mutually consistent exchanges; "
                f"rejected={rejected}, limit={self.maximum_deviation_percent}%"
            )
        price = float(statistics.median(item.price for item in accepted))
        maximum_deviation = max(abs(item.price - price) / price * 100 for item in accepted)
        changes = [item.change_24h_percent for item in accepted if item.change_24h_percent is not None]
        volumes = [item.volume_24h for item in accepted if item.volume_24h is not None]
        now = datetime.now(UTC)
        evidence = tuple({
            "source": item.source,
            "price": item.price,
            "received_at": item.received_at,
            "deviation_percent": round(abs(item.price - price) / price * 100, 6),
        } for item in accepted)
        result = MarketQuote(
            symbol=clean_symbol,
            price=price,
            change_24h_percent=float(statistics.median(changes)) if changes else None,
            volume_24h=sum(volumes) if volumes else None,
            source="consensus:" + ",".join(item.source for item in accepted),
            source_url="multi_exchange_public_spot_apis",
            received_at=now.isoformat(),
            received_at_unix_ms=int(now.timestamp() * 1000),
            constituents=evidence,
            deviation_percent=round(maximum_deviation, 6),
        )
        self._consensus_cache[clean_symbol] = (now_mono, result)
        return result

    def _providers(self) -> list[tuple[str, Callable[[str], MarketQuote]]]:
        return [
            ("bybit", self._fetch_bybit),
            ("binance", self._fetch_binance),
            ("okx", self._fetch_okx),
            ("kraken", self._fetch_kraken),
            ("coinbase", self._fetch_coinbase),
        ]

    def _fetch_bybit(self, symbol: str) -> MarketQuote:
        url = "https://api.bybit.com/v5/market/tickers"
        payload = self._get(url, params={"category": "spot", "symbol": symbol}).json()
        if payload.get("retCode") != 0:
            raise ValueError(payload.get("retMsg") or "Bybit returned an error")
        rows = payload["result"]["list"]
        if not rows:
            raise ValueError("Bybit returned no ticker")
        row = rows[0]
        return _make_quote(symbol, row.get("lastPrice"), _fraction_to_percent(row.get("price24hPcnt")), row.get("turnover24h"), "bybit", url)

    def _fetch_binance(self, symbol: str) -> MarketQuote:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        row = self._get(url, params={"symbol": symbol}).json()
        return _make_quote(symbol, row.get("lastPrice"), row.get("priceChangePercent"), row.get("quoteVolume"), "binance", url)

    def _fetch_okx(self, symbol: str) -> MarketQuote:
        url = "https://www.okx.com/api/v5/market/ticker"
        payload = self._get(url, params={"instId": _dash_symbol(symbol)}).json()
        if str(payload.get("code", "0")) != "0" or not payload.get("data"):
            raise ValueError(payload.get("msg") or "OKX returned no ticker")
        row = payload["data"][0]
        last = _positive_float(row.get("last"), "price")
        open24 = _optional_float(row.get("open24h"))
        change = ((last - open24) / open24 * 100) if open24 and open24 > 0 else None
        return _make_quote(symbol, last, change, row.get("volCcy24h"), "okx", url)

    def _fetch_kraken(self, symbol: str) -> MarketQuote:
        url = "https://api.kraken.com/0/public/Ticker"
        payload = self._get(url, params={"pair": _kraken_symbol(symbol)}).json()
        if payload.get("error"):
            raise ValueError("; ".join(payload["error"]))
        result = payload.get("result") or {}
        if not result:
            raise ValueError("Kraken returned no ticker")
        row = next(iter(result.values()))
        last = row.get("c", [None])[0]
        open24 = _optional_float(row.get("o"))
        price = _positive_float(last, "price")
        change = ((price - open24) / open24 * 100) if open24 and open24 > 0 else None
        volume = row.get("v", [None, None])[-1]
        return _make_quote(symbol, price, change, volume, "kraken", url)

    def _fetch_coinbase(self, symbol: str) -> MarketQuote:
        product = _dash_symbol(symbol)
        url = f"https://api.exchange.coinbase.com/products/{product}/stats"
        row = self._get(url, params={}).json()
        last = _positive_float(row.get("last"), "price")
        open24 = _optional_float(row.get("open"))
        change = ((last - open24) / open24 * 100) if open24 and open24 > 0 else None
        return _make_quote(symbol, last, change, row.get("volume"), "coinbase", url)

    def _get(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            response = self._client.get(url, params=params, timeout=self.timeout_seconds)
        else:
            response = httpx.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response


def _normalize_symbol(symbol: str) -> str:
    clean = str(symbol).strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30 or not clean.endswith("USDT"):
        raise ValueError("symbol must be a USDT ticker such as BTCUSDT")
    return clean


def _dash_symbol(symbol: str) -> str:
    return f"{symbol[:-4]}-USDT"


def _kraken_symbol(symbol: str) -> str:
    base = symbol[:-4]
    return f"{'XBT' if base == 'BTC' else base}USDT"


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


def _make_quote(symbol: str, price: Any, change_24h: Any, volume_24h: Any, source: str, source_url: str) -> MarketQuote:
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
