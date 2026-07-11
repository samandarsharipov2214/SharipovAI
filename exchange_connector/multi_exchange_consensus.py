"""Read-only multi-exchange USDT spot price consensus for Market Intelligence."""
from __future__ import annotations

import math
import os
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from .market_data import (
    MarketDataService,
    MarketQuote,
    normalize_usdt_symbol,
    positive_finite_float,
)


class ConsensusUnavailable(RuntimeError):
    """Raised when independent exchanges cannot produce reliable agreement."""


@dataclass(frozen=True, slots=True)
class ConsensusQuote:
    symbol: str
    price: float
    source_count: int
    sources: tuple[str, ...]
    rejected_sources: tuple[str, ...]
    rejection_reasons: dict[str, str]
    maximum_deviation_percent: float
    constituents: tuple[dict[str, Any], ...]
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiExchangeConsensus:
    """Return a median price after independent-source and outlier checks."""

    def __init__(self, service: MarketDataService | None = None) -> None:
        self.service = service or MarketDataService()
        self.minimum_sources = min(
            max(int(os.getenv("MARKET_CONSENSUS_MIN_SOURCES", "3")), 3),
            5,
        )
        self.max_deviation_percent = min(
            max(float(os.getenv("MARKET_CONSENSUS_MAX_DEVIATION_PERCENT", "0.35")), 0.01),
            2.0,
        )

    def quote(self, symbol: str) -> ConsensusQuote:
        clean_symbol, _base = normalize_usdt_symbol(symbol)
        providers = self._providers()
        quotes: list[MarketQuote] = []
        rejection_reasons: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="market-consensus") as pool:
            futures = {pool.submit(provider, clean_symbol): name for name, provider in providers}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    quote = future.result()
                    if quote.source != name:
                        raise ValueError("provider returned an unexpected source identity")
                    if quote.symbol != clean_symbol:
                        raise ValueError("provider returned an unexpected symbol")
                    if not quote.verified:
                        raise ValueError("provider quote is not verified")
                    positive_finite_float(quote.price, "price")
                    quotes.append(quote)
                except Exception as exc:
                    rejection_reasons[name] = f"{type(exc).__name__}: {exc}"

        if len(quotes) < self.minimum_sources:
            raise ConsensusUnavailable(
                f"insufficient independent quotes: {len(quotes)}/{len(providers)}; "
                f"rejections={_safe_rejections(rejection_reasons)}"
            )

        raw_median = positive_finite_float(
            statistics.median(item.price for item in quotes),
            "raw median price",
        )
        accepted: list[MarketQuote] = []
        for item in quotes:
            deviation = abs(item.price - raw_median) / raw_median * 100
            if not math.isfinite(deviation):
                rejection_reasons[item.source] = "non-finite deviation"
            elif deviation > self.max_deviation_percent:
                rejection_reasons[item.source] = (
                    f"outlier deviation {deviation:.6f}% exceeds {self.max_deviation_percent:.6f}%"
                )
            else:
                accepted.append(item)

        if len(accepted) < self.minimum_sources:
            raise ConsensusUnavailable(
                f"price disagreement after outlier rejection: {len(accepted)} accepted; "
                f"rejections={_safe_rejections(rejection_reasons)}"
            )

        price = positive_finite_float(
            statistics.median(item.price for item in accepted),
            "consensus price",
        )
        constituents = tuple(
            {
                "source": item.source,
                "price": item.price,
                "received_at_unix_ms": item.received_at_unix_ms,
                "deviation_percent": round(abs(item.price - price) / price * 100, 6),
            }
            for item in sorted(accepted, key=lambda value: value.source)
        )
        maximum_deviation = max(entry["deviation_percent"] for entry in constituents)
        return ConsensusQuote(
            symbol=clean_symbol,
            price=price,
            source_count=len(accepted),
            sources=tuple(entry["source"] for entry in constituents),
            rejected_sources=tuple(sorted(rejection_reasons)),
            rejection_reasons=dict(sorted(rejection_reasons.items())),
            maximum_deviation_percent=maximum_deviation,
            constituents=constituents,
        )

    def _providers(self) -> list[tuple[str, Callable[[str], MarketQuote]]]:
        return [
            ("bybit", lambda symbol: self.service.provider_quote("bybit", symbol)),
            ("binance", lambda symbol: self.service.provider_quote("binance", symbol)),
            ("okx", self._fetch_okx),
            ("kraken", self._fetch_kraken),
            ("coinbase", self._fetch_coinbase),
        ]

    def _fetch_okx(self, symbol: str) -> MarketQuote:
        clean, base = normalize_usdt_symbol(symbol)
        url = "https://www.okx.com/api/v5/market/ticker"
        payload = self.service.get_json(url, params={"instId": f"{base}-USDT"})
        row = (payload.get("data") or [None])[0]
        if str(payload.get("code", "0")) != "0" or not isinstance(row, dict):
            raise ValueError(payload.get("msg") or "OKX returned no ticker")
        return _simple_quote(clean, row.get("last"), "okx", url)

    def _fetch_kraken(self, symbol: str) -> MarketQuote:
        clean, base = normalize_usdt_symbol(symbol)
        pair = f"{'XBT' if base == 'BTC' else base}USDT"
        url = "https://api.kraken.com/0/public/Ticker"
        payload = self.service.get_json(url, params={"pair": pair})
        if payload.get("error"):
            raise ValueError("; ".join(str(item) for item in payload["error"]))
        result = payload.get("result") or {}
        if not isinstance(result, dict) or not result:
            raise ValueError("Kraken returned no ticker")
        row = next(iter(result.values()))
        if not isinstance(row, dict):
            raise ValueError("Kraken ticker has invalid structure")
        close = row.get("c")
        price = close[0] if isinstance(close, list) and close else None
        return _simple_quote(clean, price, "kraken", url)

    def _fetch_coinbase(self, symbol: str) -> MarketQuote:
        clean, base = normalize_usdt_symbol(symbol)
        url = f"https://api.exchange.coinbase.com/products/{base}-USDT/ticker"
        row = self.service.get_json(url, params={})
        return _simple_quote(clean, row.get("price"), "coinbase", url)


def _simple_quote(symbol: str, price: Any, source: str, source_url: str) -> MarketQuote:
    now = datetime.now(UTC)
    return MarketQuote(
        symbol=symbol,
        price=positive_finite_float(price, f"{source} price"),
        change_24h_percent=None,
        volume_24h=None,
        source=source,
        source_url=source_url,
        received_at=now.isoformat(),
        received_at_unix_ms=int(now.timestamp() * 1000),
    )


def _safe_rejections(rejections: dict[str, str]) -> dict[str, str]:
    return {key: value[:240] for key, value in sorted(rejections.items())}
