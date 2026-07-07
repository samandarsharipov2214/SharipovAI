"""Deterministic rules for analytical decision making.

This module contains rule evaluation only. It does not generate human-readable
explanations and does not include exchange, trading, API, AI, or business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.orchestrator import AgentResult

from .models import DecisionInput, DecisionType


MIN_CONFIDENCE: float = 60.0
BUY_CONFIDENCE: float = 80.0
MAX_PORTFOLIO_RISK: float = 80.0


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """Internal result of deterministic rule evaluation.

    Attributes:
        decision: Decision selected by the rule engine.
        positive_agents: Number of successful agents classified as positive.
        neutral_agents: Number of successful agents classified as neutral.
        successful_agents: Number of successful agents evaluated.
    """

    decision: DecisionType
    positive_agents: int
    neutral_agents: int
    successful_agents: int


def evaluate_rules(input: DecisionInput) -> RuleEvaluation:
    """Evaluate deterministic decision rules.

    Args:
        input: Typed decision input.

    Returns:
        Rule evaluation result.
    """

    successful_agents = [result for result in input.agent_results if result.success]
    positive_count = sum(
        1 for result in successful_agents if _is_positive_agent_result(result)
    )
    neutral_count = sum(
        1 for result in successful_agents if _is_neutral_agent_result(result)
    )
    successful_count = len(successful_agents)

    if input.confidence < MIN_CONFIDENCE:
        decision = DecisionType.NO_DECISION
    elif input.portfolio_risk > MAX_PORTFOLIO_RISK:
        decision = DecisionType.IGNORE
    elif (
        _has_majority(positive_count, successful_count)
        and input.confidence >= BUY_CONFIDENCE
    ):
        decision = DecisionType.BUY
    elif _has_majority(neutral_count, successful_count):
        decision = DecisionType.WATCH
    else:
        decision = DecisionType.IGNORE

    return RuleEvaluation(
        decision=decision,
        positive_agents=positive_count,
        neutral_agents=neutral_count,
        successful_agents=successful_count,
    )


def _has_majority(count: int, total: int) -> bool:
    """Return whether count is a strict majority of total.

    Args:
        count: Matching item count.
        total: Total item count.

    Returns:
        ``True`` when count is a strict majority.
    """

    return total > 0 and count > total / 2


def _is_positive_agent_result(result: AgentResult) -> bool:
    """Classify whether an agent result is positive.

    Args:
        result: Agent result to classify.

    Returns:
        ``True`` when the result indicates a positive analytical outcome.
    """

    return _contains_label(result, {"BUY", "POSITIVE", "BULLISH"})


def _is_neutral_agent_result(result: AgentResult) -> bool:
    """Classify whether an agent result is neutral.

    Args:
        result: Agent result to classify.

    Returns:
        ``True`` when the result indicates a neutral analytical outcome.
    """

    return _contains_label(result, {"WATCH", "NEUTRAL", "NO_DECISION"})


def _contains_label(result: AgentResult, labels: set[str]) -> bool:
    """Check whether an agent result contains any classification label.

    Args:
        result: Agent result to inspect.
        labels: Uppercase labels to search for.

    Returns:
        ``True`` when any label is present.
    """

    values = [
        result.summary,
        _stringify_mapping(result.data),
    ]
    normalized_text = " ".join(values).upper()
    return any(label in normalized_text for label in labels)


def _stringify_mapping(value: Mapping[str, Any]) -> str:
    """Convert a mapping into a searchable string.

    Args:
        value: Mapping to stringify.

    Returns:
        Searchable string representation.
    """

    return " ".join(str(item) for pair in value.items() for item in pair)
