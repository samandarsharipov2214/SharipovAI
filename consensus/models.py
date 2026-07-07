"""Typed models for consensus evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.orchestrator import AgentResult


class ConsensusLevel(Enum):
    """Supported consensus strength levels."""

    UNANIMOUS = "UNANIMOUS"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    CONFLICT = "CONFLICT"


@dataclass(slots=True)
class ConsensusInput:
    """Input data for consensus evaluation.

    Attributes:
        agent_results: Agent results to evaluate.
    """

    agent_results: list[AgentResult] = field(default_factory=list)


@dataclass(slots=True)
class ConsensusOutput:
    """Consensus evaluation result.

    Attributes:
        level: Consensus strength level.
        agreement: Agreement score from 0 to 100.
        positive_agents: Number of successful positive agents.
        negative_agents: Number of successful negative agents.
        neutral_agents: Number of successful neutral agents.
        failed_agents: Number of failed agents.
        summary: Human-readable consensus summary.
    """

    level: ConsensusLevel
    agreement: float
    positive_agents: int
    negative_agents: int
    neutral_agents: int
    failed_agents: int
    summary: str
