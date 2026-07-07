"""Tests for the deterministic risk engine."""

from __future__ import annotations

import pytest

from risk_engine import RiskEngine, RiskEngineError, RiskInput, RiskLevel


def test_evaluate_low_risk() -> None:
    """Low score returns LOW risk."""

    output = RiskEngine().evaluate(_input(5.0))

    assert output.risk_score == 5.0
    assert output.risk_level is RiskLevel.LOW
    assert output.allowed is True


def test_evaluate_medium_risk() -> None:
    """Medium score returns MEDIUM risk."""

    output = RiskEngine().evaluate(_input(40.0))

    assert output.risk_score == 40.0
    assert output.risk_level is RiskLevel.MEDIUM


def test_evaluate_high_risk() -> None:
    """High score returns HIGH risk."""

    output = RiskEngine().evaluate(_input(70.0))

    assert output.risk_score == 70.0
    assert output.risk_level is RiskLevel.HIGH


def test_evaluate_critical_risk() -> None:
    """Critical score returns CRITICAL risk."""

    output = RiskEngine().evaluate(_input(90.0))

    assert output.risk_score == 90.0
    assert output.risk_level is RiskLevel.CRITICAL


def test_evaluate_drawdown_blocks_action() -> None:
    """Portfolio drawdown at 10 or above blocks action."""

    output = RiskEngine().evaluate(
        RiskInput(
            portfolio_drawdown=10.0,
            portfolio_exposure=0.0,
            asset_exposure=0.0,
            volatility_score=0.0,
            liquidity_score=100.0,
            correlation_score=0.0,
        )
    )

    assert output.allowed is False
    assert "portfolio_drawdown" in output.reason


def test_evaluate_critical_risk_blocks_action() -> None:
    """Critical risk level blocks action."""

    output = RiskEngine().evaluate(_input(100.0))

    assert output.risk_level is RiskLevel.CRITICAL
    assert output.allowed is False
    assert "CRITICAL" in output.reason


def test_evaluate_liquidity_risk_conversion() -> None:
    """Lower liquidity score increases liquidity risk."""

    high_liquidity = RiskEngine().evaluate(
        RiskInput(0.0, 0.0, 0.0, 0.0, 100.0, 0.0)
    )
    low_liquidity = RiskEngine().evaluate(
        RiskInput(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    )

    assert high_liquidity.risk_score == 0.0
    assert low_liquidity.risk_score == 10.0


def test_evaluate_all_warning_types() -> None:
    """All configured warning thresholds are emitted."""

    output = RiskEngine().evaluate(
        RiskInput(
            portfolio_drawdown=8.0,
            portfolio_exposure=70.0,
            asset_exposure=30.0,
            volatility_score=70.0,
            liquidity_score=40.0,
            correlation_score=70.0,
        )
    )

    assert len(output.warnings) == 6
    assert any("Drawdown warning" in warning for warning in output.warnings)
    assert any("Exposure warning" in warning for warning in output.warnings)
    assert any("Asset concentration warning" in warning for warning in output.warnings)
    assert any("Volatility warning" in warning for warning in output.warnings)
    assert any("Liquidity warning" in warning for warning in output.warnings)
    assert any("Correlation warning" in warning for warning in output.warnings)


def test_evaluate_invalid_negative_input() -> None:
    """Negative values are invalid."""

    with pytest.raises(RiskEngineError):
        RiskEngine().evaluate(
            RiskInput(-1.0, 0.0, 0.0, 0.0, 100.0, 0.0)
        )


def test_evaluate_values_above_100_are_invalid() -> None:
    """Values above 100 are invalid."""

    with pytest.raises(RiskEngineError):
        RiskEngine().evaluate(
            RiskInput(0.0, 101.0, 0.0, 0.0, 100.0, 0.0)
        )


def _input(value: float) -> RiskInput:
    """Create a balanced risk input.

    Args:
        value: Value used for each direct risk component.

    Returns:
        Risk input with liquidity score inverted to match the target risk.
    """

    return RiskInput(
        portfolio_drawdown=value,
        portfolio_exposure=value,
        asset_exposure=value,
        volatility_score=value,
        liquidity_score=100.0 - value,
        correlation_score=value,
    )
