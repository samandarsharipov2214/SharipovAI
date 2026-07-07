"""Deterministic market scoring utilities.

Scores are calculated from public ticker metrics only. This module does not
include AI behavior, randomness, trading logic, or recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

from bybit import TickerInfo


@dataclass(frozen=True, slots=True)
class _ScoringContext:
    """Internal relative scoring context."""

    max_turnover_24h: Decimal
    max_abs_price_change_24h: Decimal


class MarketScorer:
    """Scores ticker models using deterministic market-data metrics."""

    MIN_SCORE: Decimal = Decimal("0")
    MAX_SCORE: Decimal = Decimal("100")
    TURNOVER_WEIGHT: Decimal = Decimal("0.70")
    PRICE_CHANGE_WEIGHT: Decimal = Decimal("0.30")

    def __init__(self) -> None:
        """Initialize the scorer with no market-relative context."""

        self._context: _ScoringContext | None = None

    def score(self, ticker: TickerInfo) -> float:
        """Calculate a deterministic score from 0 to 100.

        When ``rank`` has been called on this scorer instance, the score uses
        the latest market-relative ranking context. Otherwise, the provided
        ticker is used as a standalone context.

        Args:
            ticker: Ticker model to score.

        Returns:
            Score between 0 and 100.
        """

        context = self._context or _ScoringContext(
            max_turnover_24h=max(_parse_decimal(ticker.turnover_24h), self.MIN_SCORE),
            max_abs_price_change_24h=max(
                abs(_parse_decimal(ticker.price_24h_change_percent)),
                self.MIN_SCORE,
            ),
        )
        return self._score_with_context(ticker, context)

    def rank(self, tickers: Sequence[TickerInfo]) -> list[TickerInfo]:
        """Sort tickers by deterministic score in descending order.

        Args:
            tickers: Ticker models to rank.

        Returns:
            All ticker models sorted by score from highest to lowest.
        """

        context = self._build_context(tickers)
        self._context = context
        return sorted(
            tickers,
            key=lambda ticker: self._score_with_context(ticker, context),
            reverse=True,
        )

    def _build_context(self, tickers: Sequence[TickerInfo]) -> _ScoringContext:
        """Build a relative scoring context from a ticker list.

        Args:
            tickers: Ticker models used to calculate relative maxima.

        Returns:
            Scoring context containing maximum observed values.
        """

        max_turnover = self.MIN_SCORE
        max_abs_price_change = self.MIN_SCORE

        for ticker in tickers:
            max_turnover = max(max_turnover, _parse_decimal(ticker.turnover_24h))
            max_abs_price_change = max(
                max_abs_price_change,
                abs(_parse_decimal(ticker.price_24h_change_percent)),
            )

        return _ScoringContext(
            max_turnover_24h=max_turnover,
            max_abs_price_change_24h=max_abs_price_change,
        )

    def _score_with_context(
        self,
        ticker: TickerInfo,
        context: _ScoringContext,
    ) -> float:
        """Calculate a ticker score using a relative scoring context.

        Args:
            ticker: Ticker model to score.
            context: Relative scoring context.

        Returns:
            Score between 0 and 100.
        """

        turnover_score = self._score_relative(
            value=_parse_decimal(ticker.turnover_24h),
            maximum=context.max_turnover_24h,
        )
        price_change_score = self._score_relative(
            value=abs(_parse_decimal(ticker.price_24h_change_percent)),
            maximum=context.max_abs_price_change_24h,
        )
        score = (
            turnover_score * self.TURNOVER_WEIGHT
            + price_change_score * self.PRICE_CHANGE_WEIGHT
        )
        return float(_clamp(score, self.MIN_SCORE, self.MAX_SCORE))

    def _score_relative(self, value: Decimal, maximum: Decimal) -> Decimal:
        """Calculate a relative component score.

        Args:
            value: Component value for the ticker.
            maximum: Maximum component value in the scoring context.

        Returns:
            Component score from 0 to 100.
        """

        if value <= 0 or maximum <= 0:
            return self.MIN_SCORE

        normalized = value / maximum
        return _clamp(normalized * self.MAX_SCORE, self.MIN_SCORE, self.MAX_SCORE)


def _parse_decimal(value: str | None) -> Decimal:
    """Parse an optional decimal string.

    Args:
        value: Optional numeric string.

    Returns:
        Parsed decimal value, or zero when missing or invalid.
    """

    if value is None:
        return Decimal("0")

    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    """Clamp a decimal value between a minimum and maximum.

    Args:
        value: Value to clamp.
        minimum: Lower bound.
        maximum: Upper bound.

    Returns:
        Clamped decimal value.
    """

    return max(minimum, min(value, maximum))
