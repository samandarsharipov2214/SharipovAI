"""Deterministic portfolio risk evaluation engine.

This module evaluates typed risk inputs only. It does not include AI calls, API
calls, exchange logic, trading execution, or business logic.
"""

from __future__ import annotations

from .exceptions import RiskEngineError
from .models import RiskInput, RiskLevel, RiskOutput


class RiskEngine:
    """Evaluates deterministic risk scores and risk permissions."""

    DRAWDOWN_WEIGHT: float = 0.30
    PORTFOLIO_EXPOSURE_WEIGHT: float = 0.20
    ASSET_EXPOSURE_WEIGHT: float = 0.15
    VOLATILITY_WEIGHT: float = 0.15
    LIQUIDITY_RISK_WEIGHT: float = 0.10
    CORRELATION_WEIGHT: float = 0.10

    def evaluate(self, input: RiskInput) -> RiskOutput:
        """Evaluate risk from weighted components.

        Args:
            input: Typed risk input.

        Returns:
            Risk evaluation output.

        Raises:
            RiskEngineError: If infrastructure input is invalid.
        """

        self._validate_input(input)

        liquidity_risk = 100.0 - input.liquidity_score
        risk_score = round(
            _clamp(
                (input.portfolio_drawdown * self.DRAWDOWN_WEIGHT)
                + (input.portfolio_exposure * self.PORTFOLIO_EXPOSURE_WEIGHT)
                + (input.asset_exposure * self.ASSET_EXPOSURE_WEIGHT)
                + (input.volatility_score * self.VOLATILITY_WEIGHT)
                + (liquidity_risk * self.LIQUIDITY_RISK_WEIGHT)
                + (input.correlation_score * self.CORRELATION_WEIGHT)
            ),
            2,
        )
        risk_level = self._risk_level(risk_score)
        allowed = self._is_allowed(input, risk_level)
        warnings = self._warnings(input)

        return RiskOutput(
            risk_score=risk_score,
            risk_level=risk_level,
            allowed=allowed,
            reason=self._reason(input, risk_score, risk_level, allowed),
            warnings=warnings,
        )

    def _validate_input(self, input: RiskInput) -> None:
        """Validate risk input.

        Args:
            input: Candidate risk input.

        Raises:
            RiskEngineError: If the input object is invalid.
        """

        if not isinstance(input, RiskInput):
            raise RiskEngineError("RiskEngine requires a RiskInput instance.")

        values = {
            "portfolio_drawdown": input.portfolio_drawdown,
            "portfolio_exposure": input.portfolio_exposure,
            "asset_exposure": input.asset_exposure,
            "volatility_score": input.volatility_score,
            "liquidity_score": input.liquidity_score,
            "correlation_score": input.correlation_score,
        }

        for name, value in values.items():
            if value < 0:
                raise RiskEngineError(f"{name} must not be negative.")
            if value > 100:
                raise RiskEngineError(f"{name} must not be above 100.")

    def _risk_level(self, risk_score: float) -> RiskLevel:
        """Determine risk level from risk score.

        Args:
            risk_score: Risk score from 0 to 100.

        Returns:
            Risk level.
        """

        if risk_score < 30:
            return RiskLevel.LOW

        if risk_score < 60:
            return RiskLevel.MEDIUM

        if risk_score < 80:
            return RiskLevel.HIGH

        return RiskLevel.CRITICAL

    def _is_allowed(self, input: RiskInput, risk_level: RiskLevel) -> bool:
        """Return whether risk rules allow the analytical action.

        Args:
            input: Typed risk input.
            risk_level: Evaluated risk level.

        Returns:
            ``True`` when risk rules allow the action.
        """

        if input.portfolio_drawdown >= 10:
            return False

        return risk_level is not RiskLevel.CRITICAL

    def _warnings(self, input: RiskInput) -> list[str]:
        """Generate risk warnings.

        Args:
            input: Typed risk input.

        Returns:
            Warning messages.
        """

        warnings: list[str] = []

        if input.portfolio_drawdown >= 8:
            warnings.append("Drawdown warning: portfolio_drawdown is at least 8.")

        if input.portfolio_exposure >= 70:
            warnings.append("Exposure warning: portfolio_exposure is at least 70.")

        if input.asset_exposure >= 30:
            warnings.append(
                "Asset concentration warning: asset_exposure is at least 30."
            )

        if input.volatility_score >= 70:
            warnings.append("Volatility warning: volatility_score is at least 70.")

        if input.liquidity_score <= 40:
            warnings.append("Liquidity warning: liquidity_score is at most 40.")

        if input.correlation_score >= 70:
            warnings.append("Correlation warning: correlation_score is at least 70.")

        return warnings

    def _reason(
        self,
        input: RiskInput,
        risk_score: float,
        risk_level: RiskLevel,
        allowed: bool,
    ) -> str:
        """Generate a human-readable risk reason.

        Args:
            input: Typed risk input.
            risk_score: Evaluated risk score.
            risk_level: Evaluated risk level.
            allowed: Whether risk rules allow the action.

        Returns:
            Human-readable explanation.
        """

        if input.portfolio_drawdown >= 10:
            return (
                f"Risk level is {risk_level.value} with score {risk_score:.2f}. "
                "Action is blocked because portfolio_drawdown is at least 10."
            )

        if risk_level is RiskLevel.CRITICAL:
            return (
                f"Risk level is {risk_level.value} with score {risk_score:.2f}. "
                "Action is blocked because risk level is CRITICAL."
            )

        status = "allowed" if allowed else "blocked"
        return (
            f"Risk level is {risk_level.value} with score {risk_score:.2f}. "
            f"Action is {status} by risk rules."
        )


def _clamp(value: float) -> float:
    """Clamp a value to the 0..100 range."""

    return max(0.0, min(value, 100.0))
