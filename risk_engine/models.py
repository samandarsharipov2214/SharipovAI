"""Typed models for risk evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    """Supported risk levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class RiskInput:
    """Input data required for risk evaluation.

    Attributes:
        portfolio_drawdown: Current portfolio drawdown score from 0 to 100.
        portfolio_exposure: Portfolio exposure score from 0 to 100.
        asset_exposure: Single-asset exposure score from 0 to 100.
        volatility_score: Volatility risk score from 0 to 100.
        liquidity_score: Good-liquidity score from 0 to 100.
        correlation_score: Correlation risk score from 0 to 100.
    """

    portfolio_drawdown: float
    portfolio_exposure: float
    asset_exposure: float
    volatility_score: float
    liquidity_score: float
    correlation_score: float


@dataclass(slots=True)
class RiskOutput:
    """Risk evaluation output.

    Attributes:
        risk_score: Final risk score from 0 to 100.
        risk_level: Risk level derived from the score.
        allowed: Whether the analytical action is allowed by risk rules.
        reason: Human-readable explanation.
        warnings: Risk warnings generated during evaluation.
    """

    risk_score: float
    risk_level: RiskLevel
    allowed: bool
    reason: str
    warnings: list[str] = field(default_factory=list)
