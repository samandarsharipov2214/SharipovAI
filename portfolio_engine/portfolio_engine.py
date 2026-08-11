"""Deterministic portfolio evaluation engine.

This module evaluates typed portfolio data only. It does not include AI calls,
API calls, exchange logic, or trading execution.
"""

from __future__ import annotations

import math

from .exceptions import PortfolioEngineError
from .models import PortfolioInput, PortfolioOutput, Position


class PortfolioEngine:
    """Evaluates portfolio value, exposure, and concentration."""

    EXPOSURE_WARNING_THRESHOLD: float = 80.0
    CONCENTRATION_WARNING_THRESHOLD: float = 30.0

    def evaluate(self, input: PortfolioInput) -> PortfolioOutput:
        """Evaluate a portfolio."""

        self._validate_input(input)
        position_values = [
            (position, self._position_value(position))
            for position in input.positions
        ]
        positions_value = sum(value for _, value in position_values)
        total_value = input.cash + positions_value
        exposure_percent = _percent(positions_value, total_value)
        largest_position, largest_position_value = self._largest_position(position_values)
        largest_position_percent = _percent(largest_position_value, total_value)
        warnings = self._warnings(
            cash=input.cash,
            total_value=total_value,
            exposure_percent=exposure_percent,
            largest_position_percent=largest_position_percent,
        )

        return PortfolioOutput(
            total_value=round(total_value, 2),
            cash=round(input.cash, 2),
            positions_value=round(positions_value, 2),
            exposure_percent=round(exposure_percent, 2),
            positions_count=len(input.positions),
            largest_position_symbol=largest_position.symbol if largest_position is not None else None,
            largest_position_percent=round(largest_position_percent, 2),
            warnings=warnings,
        )

    def _validate_input(self, input: PortfolioInput) -> None:
        """Fail closed on malformed portfolio evidence before doing arithmetic."""

        if not isinstance(input, PortfolioInput):
            raise PortfolioEngineError("PortfolioEngine requires a PortfolioInput instance.")
        if not _is_finite_number(input.cash):
            raise PortfolioEngineError("Portfolio cash must be a finite number.")

        for position in input.positions:
            if not isinstance(position, Position):
                raise PortfolioEngineError("Portfolio positions must contain Position instances.")
            if not str(position.symbol).strip():
                raise PortfolioEngineError("Position symbol must not be empty.")
            for field_name in ("quantity", "average_price", "current_price"):
                value = getattr(position, field_name)
                if not _is_finite_number(value):
                    raise PortfolioEngineError(
                        f"Position '{position.symbol}' has non-finite {field_name}."
                    )
            if position.quantity < 0:
                raise PortfolioEngineError(f"Position '{position.symbol}' has negative quantity.")
            if position.average_price < 0:
                raise PortfolioEngineError(f"Position '{position.symbol}' has negative average_price.")
            if position.current_price < 0:
                raise PortfolioEngineError(f"Position '{position.symbol}' has negative current_price.")

    def _position_value(self, position: Position) -> float:
        return position.quantity * position.current_price

    def _largest_position(
        self,
        position_values: list[tuple[Position, float]],
    ) -> tuple[Position | None, float]:
        if not position_values:
            return None, 0.0
        return max(position_values, key=lambda item: item[1])

    def _warnings(
        self,
        *,
        cash: float,
        total_value: float,
        exposure_percent: float,
        largest_position_percent: float,
    ) -> list[str]:
        warnings: list[str] = []
        if cash < 0:
            warnings.append("Cash warning: cash balance is negative.")
        if total_value <= 0:
            warnings.append("Total value warning: total_value is zero or negative.")
        if exposure_percent >= self.EXPOSURE_WARNING_THRESHOLD:
            warnings.append("Exposure warning: exposure_percent is at least 80.")
        if largest_position_percent >= self.CONCENTRATION_WARNING_THRESHOLD:
            warnings.append("Concentration warning: largest_position_percent is at least 30.")
        return warnings


def _percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
