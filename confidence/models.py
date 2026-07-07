"""Typed models for confidence calculation."""

from __future__ import annotations

from dataclasses import dataclass, field

from analysis import FactorScore


@dataclass(slots=True)
class ConfidenceInput:
    """Input data required to calculate confidence.

    Attributes:
        consensus_agreement: Consensus agreement score from 0 to 100.
        factor_scores: Factor scores used in analytical evaluation.
        failed_agents: Number of failed agents.
        total_agents: Total number of agents involved.
        data_quality: Data quality score from 0 to 100.
    """

    consensus_agreement: float
    factor_scores: list[FactorScore] = field(default_factory=list)
    failed_agents: int = 0
    total_agents: int = 0
    data_quality: float = 0.0


@dataclass(slots=True)
class ConfidenceOutput:
    """Calculated confidence output.

    Attributes:
        confidence: Final confidence score from 0 to 100.
        level: Human-readable confidence level.
        reason: Human-readable explanation for the calculated score.
        warnings: Non-fatal warnings generated during calculation.
    """

    confidence: float
    level: str
    reason: str
    warnings: list[str] = field(default_factory=list)
