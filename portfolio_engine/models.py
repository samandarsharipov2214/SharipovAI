"""Typed models for portfolio evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Position:
    """Portfolio position.

    Attributes:
        symbol: Position symbol.
        quantity: Asset quantity.
        average_price: Average acquisition price.
        current_price: Current market price.
    """

    symbol: str
    quantity: float
    average_price: float
    current_price: float


@dataclass(slots=True)
class PortfolioInput:
    """Portfolio evaluation input.

    Attributes:
        cash: Cash balance.
        positions: Portfolio positions.
    """

    cash: float
    positions: list[Position] = field(default_factory=list)


@dataclass(slots=True)
class PortfolioOutput:
    """Portfolio evaluation output.

    Attributes:
        total_value: Cash plus current value of all positions.
        cash: Cash balance.
        positions_value: Current value of all positions.
        exposure_percent: Position exposure as percent of total value.
        positions_count: Number of positions.
        largest_position_symbol: Symbol of the largest position, when present.
        largest_position_percent: Largest position as percent of total value.
        warnings: Portfolio warnings generated during evaluation.
    """

    total_value: float
    cash: float
    positions_value: float
    exposure_percent: float
    positions_count: int
    largest_position_symbol: str | None
    largest_position_percent: float
    warnings: list[str] = field(default_factory=list)
