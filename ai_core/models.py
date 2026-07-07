"""Typed models for AI Core pipeline coordination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from confidence import ConfidenceOutput
from consensus import ConsensusOutput
from core.orchestrator import AgentResult
from decision import DecisionOutput
from portfolio_engine import PortfolioInput, PortfolioOutput
from risk_engine import RiskInput, RiskOutput


@dataclass(frozen=True, slots=True)
class AICoreInput:
    """Input for the complete analytical pipeline.

    Attributes:
        context: Shared execution context for registered agents.
        portfolio: Portfolio input for portfolio evaluation.
        risk: Risk input for risk evaluation.
    """

    context: Mapping[str, Any]
    portfolio: PortfolioInput
    risk: RiskInput


@dataclass(frozen=True, slots=True)
class AICoreOutput:
    """Output from the complete analytical pipeline.

    Attributes:
        agent_results: Ordered agent execution results.
        consensus: Consensus evaluation output.
        confidence: Confidence evaluation output.
        portfolio: Portfolio evaluation output.
        risk: Risk evaluation output.
        decision: Final analytical decision output.
    """

    agent_results: list[AgentResult]
    consensus: ConsensusOutput
    confidence: ConfidenceOutput
    portfolio: PortfolioOutput
    risk: RiskOutput
    decision: DecisionOutput
