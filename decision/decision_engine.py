"""Deterministic analytical decision engine.

This module contains decision orchestration rules only. It does not include
exchange logic, trading execution, API calls, AI model calls, or business logic.
"""

from __future__ import annotations

from .explainability import generate_reason, generate_warnings
from .exceptions import DecisionEngineError
from .models import DecisionInput, DecisionOutput
from .rules import evaluate_rules


class DecisionEngine:
    """Makes deterministic analytical decisions from typed input models."""

    def make_decision(self, input: DecisionInput) -> DecisionOutput:
        """Make an analytical decision.

        Normal analytical outcomes are returned as ``DecisionOutput`` values
        rather than raised as exceptions.

        Args:
            input: Typed decision input.

        Returns:
            Deterministic analytical decision output.
        """

        self._validate_input(input)
        evaluation = evaluate_rules(input)
        reason = generate_reason(input, evaluation)
        warnings = generate_warnings(input)

        return DecisionOutput(
            decision=evaluation.decision,
            confidence=input.confidence,
            reason=reason,
            warnings=warnings,
        )

    def _validate_input(self, input: DecisionInput) -> None:
        """Validate decision input structure.

        Args:
            input: Candidate decision input.

        Raises:
            DecisionEngineError: If the input object is invalid.
        """

        if not isinstance(input, DecisionInput):
            raise DecisionEngineError("DecisionEngine requires a DecisionInput instance.")

        if input.confidence < 0:
            raise DecisionEngineError("Decision confidence must not be negative.")

        if input.portfolio_risk < 0:
            raise DecisionEngineError("Portfolio risk must not be negative.")
