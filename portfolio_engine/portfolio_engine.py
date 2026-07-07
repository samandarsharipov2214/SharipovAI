"""Deterministic portfolio evaluation engine.

This module evaluates typed portfolio data only. It does not include AI calls,
API calls, exchange logic, or trading execution.
"""

from __future__ import annotations

from .exceptions import PortfolioEngineError
from .models import PortfolioInput, PortfolioOutput, Position


class PortfolioEngine:
    """Evaluates portfolio value, exposure, and concentration."""

    EXPOSURE_WARNING_THRESHOLD: float = 80.0
    CONCENTRATION_WARNING_THRESHOLD: float = 30.0

    def evaluate(self, input: PortfolioInput) -> PortfolioOutput:
        """Evaluate a portfolio.

        Args:
            input: Typed portfolio input.

        Returns:
            Portfolio evaluation output.

        Raises:
            PortfolioEngineError: If infrastructure input is invalid.
        """

        self._validate_input(input)

        position_values = [
            (position, self._position_value(position))
            for position in input.positions
        ]
        positions_value = sum(value for _, value in position_values)
        total_value = input.cash + positions_value
        exposure_percent = _percent(positions_value, total_value)
        largest_position, largest_position_value = self._largest_position(
            position_values
        )
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
            largest_position_symbol=largest_position.symbol
            if largest_position is not None
            else None,
            largest_position_percent=round(largest_position_percent, 2),
            warnings=warnings,
        )

    def _validate_input(self, input: PortfolioInput) -> None:
        """Validate portfolio input.

        Args:
            input: Candidate portfolio input.

        Raises:
            PortfolioEngineError: If the input object is invalid.
        """

        if not isinstance(input, PortfolioInput):
            raise PortfolioEngineError(
                "PortfolioEngine requires a PortfolioInput instance."
            )

        for position in input.positions:
            if position.quantity < 0:
                raise PortfolioEngineError(
                    f"Position '{position.symbol}' has negative quantity."
                )
            if position.average_price < 0:
                raise PortfolioEngineError(
                    f"Position '{position.symbol}' has negative average_price."
                )
            if position.current_price < 0:
                raise PortfolioEngineError(
                    f"Position '{position.symbol}' has negative current_price."
                )

    def _position_value(self, position: Position) -> float:
        """Calculate current position value.

        Args:
            position: Portfolio position.

        Returns:
            Current position value.
        """

        return position.quantity * position.current_price

    def _largest_position(
        self,
        position_values: list[tuple[Position, float]],
    ) -> tuple[Position | None, float]:
        """Find the largest position by current value.

        Args:
            position_values: Position and current value pairs.

        Returns:
            Largest position and value. Returns ``None`` and zero when there
            are no positions.
        """

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
        """Generate portfolio warnings.

        Args:
            cash: Cash balance.
            total_value: Total portfolio value.
            exposure_percent: Position exposure percent.
            largest_position_percent: Largest position percent.

        Returns:
            Warning messages.
        """

        warnings: list[str] = []

        if cash < 0:
            warnings.append("Cash warning: cash balance is negative.")

        if total_value <= 0:
            warnings.append("Total value warning: total_value is zero or negative.")

        if exposure_percent >= self.EXPOSURE_WARNING_THRESHOLD:
            warnings.append("Exposure warning: exposure_percent is at least 80.")

        if largest_position_percent >= self.CONCENTRATION_WARNING_THRESHOLD:
            warnings.append(
                "Concentration warning: largest_position_percent is at least 30."
            )

        return warnings


def _percent(numerator: float, denominator: float) -> float:
    """Calculate percentage safely.

    Args:
        numerator: Percentage numerator.
        denominator: Percentage denominator.

    Returns:
        Percentage value or zero when denominator is not positive.
    """

    if denominator <= 0:
        return 0.0

    return (numerator / denominator) * 100.0
