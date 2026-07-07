"""Live market data provider backed by Bybit public ticker data.

The provider reads public spot ticker data through an injected Bybit client and
converts it into data-layer models. It does not perform trading, order
execution, API key handling, or authenticated exchange operations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from threading import Thread
from typing import TYPE_CHECKING, Any, Protocol

from bybit import BybitClientError
from data_layer.models import DataBatch, DataItem

from .base import BaseDataProvider

if TYPE_CHECKING:
    from bybit import BybitClient, TickerInfo


class _MarketClient(Protocol):
    """Protocol for async market clients used by the provider."""

    async def get_tickers(self, category: str = "spot") -> list["TickerInfo"]:
        """Return ticker models for a market category."""


class LiveMarketProvider(BaseDataProvider):
    """Market data provider backed by an injected Bybit client."""

    PROVIDER_NAME: str = "LiveMarketProvider"

    def __init__(self, client: "BybitClient | _MarketClient") -> None:
        """Initialize the provider.

        Args:
            client: Bybit-compatible async client.
        """

        self._client = client

    def name(self) -> str:
        """Return the provider name."""

        return self.PROVIDER_NAME

    def fetch(self) -> DataBatch:
        """Fetch spot tickers and convert them into data items.

        Returns:
            Data batch containing market ticker items. Returns an empty batch
            when the market client fails.
        """

        try:
            tickers = _run_async(lambda: self._client.get_tickers("spot"))
        except (BybitClientError, RuntimeError, ValueError, TypeError):
            return DataBatch(items=[])

        return DataBatch(items=[_ticker_to_data_item(ticker) for ticker in tickers])


def _ticker_to_data_item(ticker: "TickerInfo") -> DataItem:
    """Convert a ticker model into a data item.

    Args:
        ticker: Ticker model returned by the market client.

    Returns:
        Data item representation of the ticker.
    """

    last_price = ticker.last_price
    price_change = ticker.price_24h_change_percent
    turnover = ticker.turnover_24h

    return DataItem(
        source="bybit",
        category="market",
        title=ticker.symbol,
        content=(
            f"Last price: {_display_value(last_price)}. "
            f"24h change: {_display_value(price_change)}. "
            f"24h turnover: {_display_value(turnover)}."
        ),
        url=None,
        published_at=None,
        metadata={
            "symbol": ticker.symbol,
            "last_price": last_price,
            "price_24h_change_percent": price_change,
            "turnover_24h": turnover,
        },
    )


def _run_async(factory: Callable[[], Awaitable[list["TickerInfo"]]]) -> list["TickerInfo"]:
    """Run an async market-client call from a sync provider interface.

    Args:
        factory: Callable returning an awaitable ticker request.

    Returns:
        Ticker models returned by the awaitable.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: list["TickerInfo"] | None = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(factory())
        except BaseException as exc:
            error = exc

    thread = Thread(target=runner)
    thread.start()
    thread.join()

    if error is not None:
        raise error

    return result or []


def _display_value(value: Any) -> str:
    """Convert an optional value into display text."""

    if value is None or value == "":
        return "unknown"
    return str(value)
