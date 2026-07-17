"""Deterministic risk engine with hard limits and soft position scaling."""
from __future__ import annotations

import math

from .exceptions import RiskEngineError
from .models import RiskInput, RiskLevel, RiskLimits, RiskOutput


class RiskEngine:
    """Evaluate hard capital-protection rules before the soft risk score."""

    DRAWDOWN_WEIGHT = 0.30
    PORTFOLIO_EXPOSURE_WEIGHT = 0.20
    ASSET_EXPOSURE_WEIGHT = 0.15
    VOLATILITY_WEIGHT = 0.15
    LIQUIDITY_RISK_WEIGHT = 0.10
    CORRELATION_WEIGHT = 0.10

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self._validate_limits(self.limits)

    def evaluate(self, input: RiskInput) -> RiskOutput:
        self._validate_input(input)
        liquidity_risk = 100.0 - input.liquidity_score
        risk_score = round(
            _clamp(
                input.portfolio_drawdown * self.DRAWDOWN_WEIGHT
                + input.portfolio_exposure * self.PORTFOLIO_EXPOSURE_WEIGHT
                + input.asset_exposure * self.ASSET_EXPOSURE_WEIGHT
                + input.volatility_score * self.VOLATILITY_WEIGHT
                + liquidity_risk * self.LIQUIDITY_RISK_WEIGHT
                + input.correlation_score * self.CORRELATION_WEIGHT
            ),
            2,
        )
        risk_level = self._risk_level(risk_score)
        hard_blocks = self._hard_blocks(input)
        allowed = not hard_blocks and risk_level is not RiskLevel.CRITICAL
        warnings = self._warnings(input)
        multiplier = 0.0 if not allowed else self._position_size_multiplier(risk_level)
        return RiskOutput(
            risk_score=risk_score,
            risk_level=risk_level,
            allowed=allowed,
            reason=self._reason(risk_score, risk_level, hard_blocks, allowed),
            warnings=warnings,
            hard_blocks=hard_blocks,
            position_size_multiplier=multiplier,
        )

    def _hard_blocks(self, input: RiskInput) -> list[str]:
        limits = self.limits
        blocks: list[str] = []
        if input.stale_data:
            blocks.append("stale_market_data")
        if input.kill_switch_active:
            blocks.append("execution_kill_switch")
        if not input.instrument_valid:
            blocks.append("invalid_instrument_specification")
        if input.portfolio_drawdown >= limits.max_portfolio_drawdown_percent:
            blocks.append("portfolio_drawdown_limit")
        if input.daily_loss_percent >= limits.max_daily_loss_percent:
            blocks.append("daily_loss_limit")
        if input.weekly_drawdown_percent >= limits.max_weekly_drawdown_percent:
            blocks.append("weekly_drawdown_limit")
        if input.portfolio_exposure >= limits.max_portfolio_exposure_percent:
            blocks.append("portfolio_exposure_limit")
        if input.asset_exposure >= limits.max_asset_exposure_percent:
            blocks.append("asset_exposure_limit")
        if input.correlated_exposure >= limits.max_correlated_exposure_percent:
            blocks.append("correlated_exposure_limit")
        effective_max_positions = min(
            max(int(input.max_open_positions), 1),
            limits.max_open_positions,
        )
        if input.open_positions >= effective_max_positions:
            blocks.append("open_position_limit")
        if input.liquidity_score <= limits.minimum_liquidity_score:
            blocks.append("liquidity_floor")
        return blocks

    def _validate_input(self, input: RiskInput) -> None:
        if not isinstance(input, RiskInput):
            raise RiskEngineError("RiskEngine requires a RiskInput instance.")
        scores = {
            "portfolio_drawdown": input.portfolio_drawdown,
            "portfolio_exposure": input.portfolio_exposure,
            "asset_exposure": input.asset_exposure,
            "volatility_score": input.volatility_score,
            "liquidity_score": input.liquidity_score,
            "correlation_score": input.correlation_score,
            "daily_loss_percent": input.daily_loss_percent,
            "weekly_drawdown_percent": input.weekly_drawdown_percent,
            "correlated_exposure": input.correlated_exposure,
        }
        for name, value in scores.items():
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise RiskEngineError(f"{name} must be finite.")
            if value < 0:
                raise RiskEngineError(f"{name} must not be negative.")
            if value > 100:
                raise RiskEngineError(f"{name} must not be above 100.")
        if isinstance(input.open_positions, bool) or int(input.open_positions) < 0:
            raise RiskEngineError("open_positions must be a non-negative integer.")
        if isinstance(input.max_open_positions, bool) or int(input.max_open_positions) <= 0:
            raise RiskEngineError("max_open_positions must be a positive integer.")
        for name in ("stale_data", "kill_switch_active", "instrument_valid"):
            if not isinstance(getattr(input, name), bool):
                raise RiskEngineError(f"{name} must be boolean.")

    @staticmethod
    def _validate_limits(limits: RiskLimits) -> None:
        for name, value in (
            ("max_portfolio_drawdown_percent", limits.max_portfolio_drawdown_percent),
            ("max_daily_loss_percent", limits.max_daily_loss_percent),
            ("max_weekly_drawdown_percent", limits.max_weekly_drawdown_percent),
            ("max_portfolio_exposure_percent", limits.max_portfolio_exposure_percent),
            ("max_asset_exposure_percent", limits.max_asset_exposure_percent),
            ("max_correlated_exposure_percent", limits.max_correlated_exposure_percent),
            ("minimum_liquidity_score", limits.minimum_liquidity_score),
        ):
            if not math.isfinite(float(value)) or not 0 < float(value) <= 100:
                raise RiskEngineError(f"{name} must be within 0..100.")
        if limits.max_open_positions <= 0:
            raise RiskEngineError("max_open_positions must be positive.")

    @staticmethod
    def _risk_level(risk_score: float) -> RiskLevel:
        if risk_score < 30:
            return RiskLevel.LOW
        if risk_score < 60:
            return RiskLevel.MEDIUM
        if risk_score < 80:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    @staticmethod
    def _position_size_multiplier(level: RiskLevel) -> float:
        return {
            RiskLevel.LOW: 1.0,
            RiskLevel.MEDIUM: 0.6,
            RiskLevel.HIGH: 0.25,
            RiskLevel.CRITICAL: 0.0,
        }[level]

    @staticmethod
    def _warnings(input: RiskInput) -> list[str]:
        warnings: list[str] = []
        if input.portfolio_drawdown >= 8:
            warnings.append("Drawdown warning: portfolio_drawdown is at least 8.")
        if input.portfolio_exposure >= 70:
            warnings.append("Exposure warning: portfolio_exposure is at least 70.")
        if input.asset_exposure >= 30:
            warnings.append("Asset concentration warning: asset_exposure is at least 30.")
        if input.volatility_score >= 70:
            warnings.append("Volatility warning: volatility_score is at least 70.")
        if input.liquidity_score <= 40:
            warnings.append("Liquidity warning: liquidity_score is at most 40.")
        if input.correlation_score >= 70:
            warnings.append("Correlation warning: correlation_score is at least 70.")
        return warnings

    @staticmethod
    def _reason(
        risk_score: float,
        risk_level: RiskLevel,
        hard_blocks: list[str],
        allowed: bool,
    ) -> str:
        if hard_blocks:
            return (
                f"Risk level is {risk_level.value} with score {risk_score:.2f}. "
                f"Action is blocked by hard limit: {hard_blocks[0]}."
            )
        if risk_level is RiskLevel.CRITICAL:
            return (
                f"Risk level is {risk_level.value} with score {risk_score:.2f}. "
                "Action is blocked because risk level is CRITICAL."
            )
        return (
            f"Risk level is {risk_level.value} with score {risk_score:.2f}. "
            f"Action is {'allowed' if allowed else 'blocked'} by risk rules."
        )


def _clamp(value: float) -> float:
    return max(0.0, min(value, 100.0))


__all__ = ["RiskEngine"]
