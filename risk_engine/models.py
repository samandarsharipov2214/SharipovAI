"""Typed models for deterministic portfolio and execution risk evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Hard risk limits. Breaches always override a soft score."""

    max_portfolio_drawdown_percent: float = 10.0
    max_daily_loss_percent: float = 2.0
    max_weekly_drawdown_percent: float = 5.0
    max_portfolio_exposure_percent: float = 80.0
    max_asset_exposure_percent: float = 25.0
    max_correlated_exposure_percent: float = 35.0
    minimum_liquidity_score: float = 20.0
    max_open_positions: int = 5


@dataclass(slots=True)
class RiskInput:
    """Risk state normalized to percentages/scores in the 0..100 range."""

    portfolio_drawdown: float
    portfolio_exposure: float
    asset_exposure: float
    volatility_score: float
    liquidity_score: float
    correlation_score: float
    daily_loss_percent: float = 0.0
    weekly_drawdown_percent: float = 0.0
    correlated_exposure: float = 0.0
    open_positions: int = 0
    max_open_positions: int = 5
    stale_data: bool = False
    kill_switch_active: bool = False
    instrument_valid: bool = True


@dataclass(slots=True)
class RiskOutput:
    risk_score: float
    risk_level: RiskLevel
    allowed: bool
    reason: str
    warnings: list[str] = field(default_factory=list)
    hard_blocks: list[str] = field(default_factory=list)
    position_size_multiplier: float = 0.0


__all__ = ["RiskInput", "RiskLevel", "RiskLimits", "RiskOutput"]
