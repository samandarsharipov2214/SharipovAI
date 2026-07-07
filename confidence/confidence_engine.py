"""Deterministic confidence calculation engine.

This module calculates confidence from typed analytical inputs only. It does
not include AI calls, API calls, exchange logic, or trading execution.
"""

from __future__ import annotations

from .exceptions import ConfidenceEngineError
from .models import ConfidenceInput, ConfidenceOutput


class ConfidenceEngine:
    """Calculates deterministic confidence scores."""

    CONSENSUS_WEIGHT: float = 0.40
    FACTOR_WEIGHT: float = 0.30
    DATA_QUALITY_WEIGHT: float = 0.20
    AGENT_RELIABILITY_WEIGHT: float = 0.10

    def calculate(self, input: ConfidenceInput) -> ConfidenceOutput:
        """Calculate confidence from weighted components.

        Args:
            input: Typed confidence input.

        Returns:
            Calculated confidence output.

        Raises:
            ConfidenceEngineError: If infrastructure input is invalid.
        """

        self._validate_input(input)

        average_factor_score = self._average_factor_score(input)
        agent_reliability = self._agent_reliability(input)
        confidence = _clamp(
            (input.consensus_agreement * self.CONSENSUS_WEIGHT)
            + (average_factor_score * self.FACTOR_WEIGHT)
            + (input.data_quality * self.DATA_QUALITY_WEIGHT)
            + (agent_reliability * self.AGENT_RELIABILITY_WEIGHT)
        )
        confidence = round(confidence, 2)
        level = self._level(confidence)
        warnings = self._warnings(input)

        return ConfidenceOutput(
            confidence=confidence,
            level=level,
            reason=(
                "Confidence calculated from weighted components: "
                f"consensus={input.consensus_agreement:.2f}, "
                f"average_factor_score={average_factor_score:.2f}, "
                f"data_quality={input.data_quality:.2f}, "
                f"agent_reliability={agent_reliability:.2f}."
            ),
            warnings=warnings,
        )

    def _validate_input(self, input: ConfidenceInput) -> None:
        """Validate confidence input.

        Args:
            input: Candidate confidence input.

        Raises:
            ConfidenceEngineError: If the input object is invalid.
        """

        if not isinstance(input, ConfidenceInput):
            raise ConfidenceEngineError(
                "ConfidenceEngine requires a ConfidenceInput instance."
            )

        if input.failed_agents < 0:
            raise ConfidenceEngineError("failed_agents must not be negative.")

        if input.total_agents < 0:
            raise ConfidenceEngineError("total_agents must not be negative.")

        if input.failed_agents > input.total_agents and input.total_agents > 0:
            raise ConfidenceEngineError(
                "failed_agents must not exceed total_agents."
            )

    def _average_factor_score(self, input: ConfidenceInput) -> float:
        """Calculate average factor score.

        Args:
            input: Typed confidence input.

        Returns:
            Average factor score from 0 to 100.
        """

        if not input.factor_scores:
            return 0.0

        total = sum(_clamp(factor.score) for factor in input.factor_scores)
        return total / len(input.factor_scores)

    def _agent_reliability(self, input: ConfidenceInput) -> float:
        """Calculate agent reliability.

        Args:
            input: Typed confidence input.

        Returns:
            Agent reliability score from 0 to 100.
        """

        if input.total_agents == 0:
            return 0.0

        return _clamp(
            ((input.total_agents - input.failed_agents) / input.total_agents) * 100
        )

    def _warnings(self, input: ConfidenceInput) -> list[str]:
        """Generate confidence warnings.

        Args:
            input: Typed confidence input.

        Returns:
            Warning messages.
        """

        warnings: list[str] = []

        if input.data_quality < 50:
            warnings.append("Low data quality: data_quality is below 50.")

        if input.failed_agents > 0:
            warnings.append(f"Failed agents detected: {input.failed_agents}.")

        if input.total_agents == 0:
            warnings.append("No agents were provided; agent reliability is 0.")

        if not input.factor_scores:
            warnings.append("No factor scores were provided.")

        if input.consensus_agreement < 50:
            warnings.append("Low consensus: consensus_agreement is below 50.")

        return warnings

    def _level(self, confidence: float) -> str:
        """Return confidence level for a score.

        Args:
            confidence: Confidence score from 0 to 100.

        Returns:
            Confidence level.
        """

        if confidence >= 80:
            return "HIGH"

        if confidence >= 60:
            return "MEDIUM"

        if confidence >= 40:
            return "LOW"

        return "VERY_LOW"


def _clamp(value: float) -> float:
    """Clamp a value to the 0..100 range."""

    return max(0.0, min(value, 100.0))
