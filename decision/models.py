"""Typed models for analytical decision making."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from analysis import FactorScore
from core.orchestrator import AgentResult


class DecisionType(Enum):
    """Supported analytical decision types."""

    BUY = "BUY"
    SELL = "SELL"
    WATCH = "WATCH"
    IGNORE = "IGNORE"
    NO_DECISION = "NO_DECISION"


@dataclass(slots=True)
class DecisionInput:
    """Input data required by the decision engine.

    Attributes:
        agent_results: Results produced by registered analytical agents.
        factor_scores: Factor scores available to the decision engine.
        portfolio_risk: Portfolio risk score.
        confidence: Overall confidence score.
    """

    agent_results: list[AgentResult] = field(default_factory=list)
    factor_scores: list[FactorScore] = field(default_factory=list)
    portfolio_risk: float = 0.0
    confidence: float = 0.0


@dataclass(slots=True)
class DecisionOutput:
    """Output returned by the decision engine.

    Attributes:
        decision: Analytical decision type.
        confidence: Confidence score used for the decision.
        reason: Human-readable decision explanation.
        warnings: Warnings generated during decision evaluation.
    """

    decision: DecisionType
    confidence: float
    reason: str
    warnings: list[str] = field(default_factory=list)
