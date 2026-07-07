"""Deterministic signal generation utilities.

Signals are rule-based labels for market analysis output only. This module does
not include AI behavior, randomness, trading execution, or recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from bybit import TickerInfo


SignalValue = Literal["BUY", "WATCH", "IGNORE"]


@dataclass(frozen=True, slots=True)
class Signal:
    """Typed market signal result.

    Attributes:
        symbol: Ticker symbol.
        score: Numeric score used for signal generation.
        signal: Generated signal label.
        reason: Deterministic explanation for the generated signal.
    """

    symbol: str
    score: float
    signal: SignalValue
    reason: str


class SignalEngine:
    """Generates deterministic market signals from ticker data and scores."""

    BUY_THRESHOLD: float = 70.0
    WATCH_THRESHOLD: float = 50.0
    MIN_BUY_TURNOVER_24H: Decimal = Decimal("1000000")
    MIN_BUY_PRICE_CHANGE_24H: Decimal = Decimal("0.01")

    def generate_signal(self, ticker: TickerInfo, score: float) -> Signal:
        """Generate a deterministic signal for a ticker.

        Args:
            ticker: Ticker model used for signal generation.
            score: Numeric market score.

        Returns:
            Typed signal result.
        """

        price_change = _parse_decimal(ticker.price_24h_change_percent)
        turnover = _parse_decimal(ticker.turnover_24h)

        if (
            score >= self.BUY_THRESHOLD
            and turnover > self.MIN_BUY_TURNOVER_24H
            and price_change > self.MIN_BUY_PRICE_CHANGE_24H
        ):
            return Signal(
                symbol=ticker.symbol,
                score=score,
                signal="BUY",
                reason=(
                    "Score is at or above 70, 24h turnover is above 1000000, "
                    "and 24h price change is above 1%."
                ),
            )

        if score >= self.WATCH_THRESHOLD:
            return Signal(
                symbol=ticker.symbol,
                score=score,
                signal="WATCH",
                reason="Score is at or above 50.",
            )

        return Signal(
            symbol=ticker.symbol,
            score=score,
            signal="IGNORE",
            reason="Score is below 50.",
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
