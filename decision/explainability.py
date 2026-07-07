"""Explainability helpers for analytical decision output."""

from __future__ import annotations

from .models import DecisionInput, DecisionType
from .rules import (
    BUY_CONFIDENCE,
    MAX_PORTFOLIO_RISK,
    MIN_CONFIDENCE,
    RuleEvaluation,
)


def generate_reason(input: DecisionInput, evaluation: RuleEvaluation) -> str:
    """Generate a human-readable reason for a decision.

    Args:
        input: Typed decision input.
        evaluation: Deterministic rule evaluation.

    Returns:
        Human-readable explanation.
    """

    if evaluation.decision is DecisionType.NO_DECISION:
        return (
            "No decision was made because confidence is below the minimum "
            f"threshold of {MIN_CONFIDENCE:g}."
        )

    if input.portfolio_risk > MAX_PORTFOLIO_RISK:
        return (
            "Decision is IGNORE because portfolio risk is above the maximum "
            f"threshold of {MAX_PORTFOLIO_RISK:g}."
        )

    if evaluation.decision is DecisionType.BUY:
        return (
            "Decision is BUY because a majority of successful agents are "
            f"positive ({evaluation.positive_agents}/"
            f"{evaluation.successful_agents}) and confidence is at least "
            f"{BUY_CONFIDENCE:g}."
        )

    if evaluation.decision is DecisionType.WATCH:
        return (
            "Decision is WATCH because a majority of successful agents are "
            f"neutral ({evaluation.neutral_agents}/"
            f"{evaluation.successful_agents})."
        )

    return (
        "Decision is IGNORE because the analytical inputs did not meet the BUY "
        "or WATCH conditions."
    )


def generate_warnings(input: DecisionInput) -> list[str]:
    """Generate non-fatal decision warnings.

    Args:
        input: Typed decision input.

    Returns:
        Human-readable warning messages.
    """

    warnings: list[str] = []

    failed_agents = [
        result.agent_name for result in input.agent_results if not result.success
    ]
    if failed_agents:
        warnings.append(
            "Some agents failed and were excluded from majority evaluation: "
            f"{', '.join(failed_agents)}."
        )

    if not any(result.success for result in input.agent_results):
        warnings.append("No successful agent results were available.")

    if not input.factor_scores:
        warnings.append("No factor scores were provided.")

    return warnings
