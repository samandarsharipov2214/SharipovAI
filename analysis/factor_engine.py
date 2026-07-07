"""Deterministic factor evaluation for market ticker data.

This module evaluates typed ticker models using transparent, rule-based factor
calculations only. It does not include AI behavior, randomness, trading logic,
or recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

from bybit import TickerInfo


@dataclass(frozen=True, slots=True)
class FactorScore:
    """Typed score for a single market factor.

    Attributes:
        name: Factor name.
        score: Factor score from 0 to 100.
        weight: Factor weight in the total factor set.
        reason: Deterministic explanation for the score.
    """

    name: str
    score: float
    weight: float
    reason: str


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Market-wide statistics used for relative factor scoring.

    Attributes:
        ticker_count: Number of tickers used to build the context.
        max_volume_24h: Maximum 24-hour volume observed in the market set.
        max_turnover_24h: Maximum 24-hour turnover observed in the market set.
        max_abs_price_change_24h: Maximum absolute 24-hour price change.
        max_positive_price_change_24h: Maximum positive 24-hour price change.
        max_spread_ratio: Widest valid bid-ask spread ratio observed.
    """

    ticker_count: int
    max_volume_24h: Decimal
    max_turnover_24h: Decimal
    max_abs_price_change_24h: Decimal
    max_positive_price_change_24h: Decimal
    max_spread_ratio: Decimal

    @classmethod
    def from_tickers(cls, tickers: Sequence[TickerInfo]) -> MarketContext:
        """Build market-wide statistics from a ticker sequence.

        Args:
            tickers: Ticker models used as the current market universe.

        Returns:
            Market-wide scoring context.
        """

        max_volume = Decimal("0")
        max_turnover = Decimal("0")
        max_abs_price_change = Decimal("0")
        max_positive_price_change = Decimal("0")
        max_spread_ratio = Decimal("0")

        for ticker in tickers:
            price_change = _parse_decimal(ticker.price_24h_change_percent)
            spread_ratio = _calculate_spread_ratio(
                bid_price=_parse_decimal(ticker.bid_price),
                ask_price=_parse_decimal(ticker.ask_price),
            )

            max_volume = max(max_volume, _parse_decimal(ticker.volume_24h))
            max_turnover = max(max_turnover, _parse_decimal(ticker.turnover_24h))
            max_abs_price_change = max(max_abs_price_change, abs(price_change))
            max_positive_price_change = max(max_positive_price_change, price_change)
            max_spread_ratio = max(max_spread_ratio, spread_ratio)

        return cls(
            ticker_count=len(tickers),
            max_volume_24h=max_volume,
            max_turnover_24h=max_turnover,
            max_abs_price_change_24h=max_abs_price_change,
            max_positive_price_change_24h=max_positive_price_change,
            max_spread_ratio=max_spread_ratio,
        )


class FactorEngine:
    """Evaluates deterministic market factors for typed ticker models."""

    VOLUME_WEIGHT: float = 0.30
    PRICE_CHANGE_WEIGHT: float = 0.20
    LIQUIDITY_WEIGHT: float = 0.20
    VOLATILITY_WEIGHT: float = 0.15
    TREND_WEIGHT: float = 0.15

    def __init__(self, context: MarketContext) -> None:
        """Initialize the engine with market-wide scoring context.

        Args:
            context: Market context used by every factor calculation.
        """

        self._context = context

    @classmethod
    def from_tickers(cls, tickers: Sequence[TickerInfo]) -> FactorEngine:
        """Create a factor engine from the current market ticker universe.

        Args:
            tickers: Ticker models used to build market-wide statistics.

        Returns:
            Factor engine configured with a market-relative context.
        """

        return cls(context=MarketContext.from_tickers(tickers))

    def evaluate(self, ticker: TickerInfo) -> list[FactorScore]:
        """Evaluate all configured factors for a ticker.

        Args:
            ticker: Typed ticker model to evaluate.

        Returns:
            List of factor scores.
        """

        return [
            self._evaluate_volume(ticker, self._context),
            self._evaluate_price_change(ticker, self._context),
            self._evaluate_liquidity(ticker, self._context),
            self._evaluate_volatility(ticker, self._context),
            self._evaluate_trend(ticker, self._context),
        ]

    def _evaluate_volume(
        self,
        ticker: TickerInfo,
        context: MarketContext,
    ) -> FactorScore:
        """Evaluate the 24-hour volume factor."""

        volume = _parse_decimal(ticker.volume_24h)
        score = _score_relative(value=volume, maximum=context.max_volume_24h)
        return FactorScore(
            name="Volume Factor",
            score=float(score),
            weight=self.VOLUME_WEIGHT,
            reason=(
                f"24h volume {_display_decimal(volume)} scored relative to "
                f"market maximum {_display_decimal(context.max_volume_24h)}."
            ),
        )

    def _evaluate_price_change(
        self,
        ticker: TickerInfo,
        context: MarketContext,
    ) -> FactorScore:
        """Evaluate the absolute 24-hour price-change factor."""

        absolute_change = abs(_parse_decimal(ticker.price_24h_change_percent))
        score = _score_relative(
            value=absolute_change,
            maximum=context.max_abs_price_change_24h,
        )
        return FactorScore(
            name="Price Change Factor",
            score=float(score),
            weight=self.PRICE_CHANGE_WEIGHT,
            reason=(
                f"Absolute 24h price change {_display_percent(absolute_change)} "
                "scored relative to the market maximum."
            ),
        )

    def _evaluate_liquidity(
        self,
        ticker: TickerInfo,
        context: MarketContext,
    ) -> FactorScore:
        """Evaluate liquidity using turnover and relative spread tightness."""

        turnover = _parse_decimal(ticker.turnover_24h)
        turnover_score = _score_relative(
            value=turnover,
            maximum=context.max_turnover_24h,
        )
        spread_score = _score_inverse_relative(
            value=_calculate_spread_ratio(
                bid_price=_parse_decimal(ticker.bid_price),
                ask_price=_parse_decimal(ticker.ask_price),
            ),
            maximum=context.max_spread_ratio,
        )
        score = _average_scores(turnover_score, spread_score)
        return FactorScore(
            name="Liquidity Factor",
            score=float(score),
            weight=self.LIQUIDITY_WEIGHT,
            reason=(
                "Liquidity scored from turnover relative to the market maximum "
                "and spread tightness relative to the market spread range."
            ),
        )

    def _evaluate_volatility(
        self,
        ticker: TickerInfo,
        context: MarketContext,
    ) -> FactorScore:
        """Evaluate volatility from relative absolute 24-hour movement."""

        absolute_change = abs(_parse_decimal(ticker.price_24h_change_percent))
        score = _score_relative(
            value=absolute_change,
            maximum=context.max_abs_price_change_24h,
        )
        return FactorScore(
            name="Volatility Factor",
            score=float(score),
            weight=self.VOLATILITY_WEIGHT,
            reason=(
                f"Volatility {_display_percent(absolute_change)} scored "
                "relative to the largest absolute market move."
            ),
        )

    def _evaluate_trend(
        self,
        ticker: TickerInfo,
        context: MarketContext,
    ) -> FactorScore:
        """Evaluate trend from relative positive 24-hour price change."""

        price_change = _parse_decimal(ticker.price_24h_change_percent)
        score = _score_relative(
            value=max(price_change, Decimal("0")),
            maximum=context.max_positive_price_change_24h,
        )
        return FactorScore(
            name="Trend Factor",
            score=float(score),
            weight=self.TREND_WEIGHT,
            reason=(
                f"Directional 24h change {_display_percent(price_change)} "
                "scored relative to the strongest positive market move."
            ),
        )


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


def _calculate_spread_ratio(bid_price: Decimal, ask_price: Decimal) -> Decimal:
    """Calculate bid-ask spread as a ratio of midpoint price.

    Args:
        bid_price: Best bid price.
        ask_price: Best ask price.

    Returns:
        Spread ratio, or zero when prices are invalid.
    """

    if bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
        return Decimal("0")

    midpoint = (bid_price + ask_price) / Decimal("2")
    if midpoint <= 0:
        return Decimal("0")

    return (ask_price - bid_price) / midpoint


def _score_relative(value: Decimal, maximum: Decimal) -> Decimal:
    """Score a value relative to a market maximum.

    Args:
        value: Value to score.
        maximum: Market maximum for the factor.

    Returns:
        Score from 0 to 100.
    """

    if value <= 0 or maximum <= 0:
        return Decimal("0")

    return _clamp((value / maximum) * Decimal("100"))


def _score_inverse_relative(value: Decimal, maximum: Decimal) -> Decimal:
    """Score lower values higher relative to a market maximum.

    Args:
        value: Value to score.
        maximum: Market maximum for the factor.

    Returns:
        Score from 0 to 100.
    """

    if maximum <= 0:
        return Decimal("100") if value == 0 else Decimal("0")

    return _clamp(Decimal("100") - ((value / maximum) * Decimal("100")))


def _average_scores(first: Decimal, second: Decimal) -> Decimal:
    """Average two factor component scores."""

    return _clamp((first + second) / Decimal("2"))


def _clamp(value: Decimal) -> Decimal:
    """Clamp a decimal value to the 0..100 score range."""

    return max(Decimal("0"), min(value, Decimal("100")))


def _display_decimal(value: Decimal) -> str:
    """Format a decimal value for reasons."""

    return f"{value.normalize():f}"


def _display_percent(value: Decimal) -> str:
    """Format a decimal ratio as a percentage string."""

    return f"{(value * Decimal('100')).normalize():f}%"
