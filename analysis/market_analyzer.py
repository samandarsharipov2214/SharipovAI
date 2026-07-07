"""Deterministic market analysis helpers.

This module contains simple data-processing utilities only. It does not include
AI behavior, trading logic, recommendations, or exchange execution.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Sequence

from bybit import TickerInfo


class MarketAnalyzer:
    """Provides deterministic analysis over typed market-data models."""

    DEFAULT_TOP_LIMIT: int = 20

    def analyze_top_volume(
        self,
        tickers: Sequence[TickerInfo],
    ) -> list[TickerInfo]:
        """Return tickers sorted by 24-hour turnover in descending order.

        Args:
            tickers: Sequence of ticker models to analyze.

        Returns:
            Up to 20 ticker models ordered by descending 24-hour turnover.
            Missing or invalid turnover values are treated as zero.
        """

        return sorted(
            tickers,
            key=lambda ticker: _parse_decimal(ticker.turnover_24h),
            reverse=True,
        )[: self.DEFAULT_TOP_LIMIT]


def _parse_decimal(value: str | None) -> Decimal:
    """Parse a decimal value from an optional string.

    Args:
        value: Numeric string to parse.

    Returns:
        Parsed decimal value, or zero when the value is missing or invalid.
    """

    if value is None:
        return Decimal("0")

    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")
