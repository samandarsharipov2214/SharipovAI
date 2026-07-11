"""Read-only multi-exchange price consensus for SharipovAI Market AI."""
from __future__ import annotations

import os
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .market_data import MarketDataService, MarketQuote


class ConsensusUnavailable(RuntimeError):
    """Raised when independent exchanges cannot produce reliable agreement."""


@dataclass(frozen=True, slots=True)
class ConsensusQuote:
    symbol: str
    price: float
    source_count: int
    sources: tuple[str, ...]
    rejected_sources: tuple[str, ...]
    maximum_deviation_percent: float
    constituents: tuple[dict[str, Any], ...]
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiExchangeConsensus:
    """Collect independent spot quotes and return a median after outlier rejection."""

    def __init__(self, service: MarketDataService | None = None) -> None:
        self.service = service or MarketDataService()
        self.minimum_sources = min(max(int(os.getenv("MARKET_CONSENSUS_MIN_SOURCES", "3")), 3), 5)
        self.max_deviation_percent = max(float(os.getenv("MARKET_CONSENSUS_MAX_DEVIATION_PERCENT", "0.35")), 0.01)

    def quote(self, symbol: str) -> ConsensusQuote:
        providers = self._providers()
        quotes: list[MarketQuote] = []
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="market-consensus") as pool:
            futures = {pool.submit(provider, symbol): name for name, provider in providers}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    quote = future.result()
                    if quote.verified and quote.price > 0:
                        quotes.append(quote)
                    else:
                        errors[name] = "unverified or non-positive quote"
                except Exception as exc:
                    errors[name] = f"{type(exc).__name__}: {exc}"

        if len(quotes) < self.minimum_sources:
            raise ConsensusUnavailable(
                f"insufficient independent quotes: {len(quotes)}/{len(providers)}; errors={errors}"
            )

        raw_median = float(statistics.median(item.price for item in quotes))
        accepted = [
            item for item in quotes
            if abs(item.price - raw_median) / raw_median * 100 <= self.max_deviation_percent
        ]
        rejected = sorted(item.source for item in quotes if item not in accepted)
        if len(accepted) < self.minimum_sources:
            raise ConsensusUnavailable(
                f"price disagreement after outlier rejection: {len(accepted)} accepted; rejected={rejected}"
            )

        price = float(statistics.median(item.price for item in accepted))
        constituents = tuple(
            {
                "source": item.source,
                "price": item.price,
                "received_at_unix_ms": item.received_at_unix_ms,
                "deviation_percent": round(abs(item.price - price) / price * 100, 6),
            }
            for item in sorted(accepted, key=lambda value: value.source)
        )
        max_deviation = max(entry["deviation_percent"] for entry in constituents)
        return ConsensusQuote(
            symbol=accepted[0].symbol,
            price=price,
            source_count=len(accepted),
            sources=tuple(entry["source"] for entry in constituents),
            rejected_sources=tuple(rejected),
            maximum_deviation_percent=max_deviation,
            constituents=constituents,
        )

    def _providers(self) -> list[tuple[str, Callable[[str], MarketQuote]]]:
        return [
            ("bybit", self.service._fetch_bybit),
            ("binance", self.service._fetch_binance),
            ("okx", self._fetch_okx),
            ("kraken", self._fetch_kraken),
            ("coinbase", self._fetch_coinbase),
        ]

    def _fetch_okx(self, symbol: str) -> MarketQuote:
        base = symbol.strip().upper().replace("/", "").replace("-", "")[:-4]
        url = "https://www.okx.com/api/v5/market/ticker"
        payload = self.service._get(url, params={"instId": f"{base}-USDT"}).json()
        row = (payload.get("data") or [None])[0]
        if str(payload.get("code", "0")) != "0" or not isinstance(row, dict):
            raise ValueError(payload.get("msg") or "OKX returned no ticker")
        return _simple_quote(symbol, row.get("last"), "okx", url)

    def _fetch_kraken(self, symbol: str) -> MarketQuote:
        base = symbol.strip().upper().replace("/", "").replace("-", "")[:-4]
        pair = f"{'XBT' if base == 'BTC' else base}USDT"
        url = "https://api.kraken.com/0/public/Ticker"
        payload = self.service._get(url, params={"pair": pair}).json()
        if payload.get("error"):
            raise ValueError("; ".join(payload["error"]))
        result = payload.get("result") or {}
        if not result:
            raise ValueError("Kraken returned no ticker")
        row = next(iter(result.values()))
        return _simple_quote(symbol, row.get("c", [None])[0], "kraken", url)

    def _fetch_coinbase(self, symbol: str) -> MarketQuote:
        base = symbol.strip().upper().replace("/", "").replace("-", "")[:-4]
        url = f"https://api.exchange.coinbase.com/products/{base}-USDT/ticker"
        row = self.service._get(url, params={}).json()
        return _simple_quote(symbol, row.get("price"), "coinbase", url)


def _simple_quote(symbol: str, price: Any, source: str, source_url: str) -> MarketQuote:
    from datetime import UTC, datetime

    parsed = float(price)
    if parsed <= 0:
        raise ValueError(f"{source} returned invalid price")
    now = datetime.now(UTC)
    return MarketQuote(
        symbol=symbol.strip().upper().replace("/", "").replace("-", ""),
        price=parsed,
        change_24h_percent=None,
        volume_24h=None,
        source=source,
        source_url=source_url,
        received_at=now.isoformat(),
        received_at_unix_ms=int(now.timestamp() * 1000),
    )
