"""Tests for the deterministic confidence engine."""

from __future__ import annotations

from analysis import FactorScore
from confidence import ConfidenceEngine, ConfidenceInput


def test_calculate_high_confidence() -> None:
    """High weighted score returns HIGH level."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=90.0,
            factor_scores=[_factor(90.0)],
            failed_agents=0,
            total_agents=4,
            data_quality=90.0,
        )
    )

    assert output.confidence == 91.0
    assert output.level == "HIGH"


def test_calculate_medium_confidence() -> None:
    """Medium weighted score returns MEDIUM level."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=70.0,
            factor_scores=[_factor(60.0)],
            failed_agents=1,
            total_agents=4,
            data_quality=70.0,
        )
    )

    assert output.confidence == 67.5
    assert output.level == "MEDIUM"


def test_calculate_low_confidence() -> None:
    """Low weighted score returns LOW level."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=50.0,
            factor_scores=[_factor(40.0)],
            failed_agents=2,
            total_agents=4,
            data_quality=50.0,
        )
    )

    assert output.confidence == 47.0
    assert output.level == "LOW"


def test_calculate_very_low_confidence() -> None:
    """Very low weighted score returns VERY_LOW level."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=20.0,
            factor_scores=[_factor(20.0)],
            failed_agents=3,
            total_agents=4,
            data_quality=20.0,
        )
    )

    assert output.confidence == 20.5
    assert output.level == "VERY_LOW"


def test_calculate_failed_agents_warning() -> None:
    """Failed agents generate a warning."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=80.0,
            factor_scores=[_factor(80.0)],
            failed_agents=1,
            total_agents=2,
            data_quality=80.0,
        )
    )

    assert any("Failed agents" in warning for warning in output.warnings)


def test_calculate_no_agents_warning() -> None:
    """No agents generate a warning and reliability is zero."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=80.0,
            factor_scores=[_factor(80.0)],
            failed_agents=0,
            total_agents=0,
            data_quality=80.0,
        )
    )

    assert any("No agents" in warning for warning in output.warnings)


def test_calculate_no_factor_scores_warning() -> None:
    """Missing factor scores generate a warning."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=80.0,
            factor_scores=[],
            failed_agents=0,
            total_agents=1,
            data_quality=80.0,
        )
    )

    assert "No factor scores were provided." in output.warnings


def test_calculate_low_data_quality_warning() -> None:
    """Low data quality generates a warning."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=80.0,
            factor_scores=[_factor(80.0)],
            failed_agents=0,
            total_agents=1,
            data_quality=49.99,
        )
    )

    assert any("Low data quality" in warning for warning in output.warnings)


def test_calculate_low_consensus_warning() -> None:
    """Low consensus generates a warning."""

    output = ConfidenceEngine().calculate(
        ConfidenceInput(
            consensus_agreement=49.99,
            factor_scores=[_factor(80.0)],
            failed_agents=0,
            total_agents=1,
            data_quality=80.0,
        )
    )

    assert any("Low consensus" in warning for warning in output.warnings)


def _factor(score: float) -> FactorScore:
    """Create a factor score."""

    return FactorScore(
        name="Test Factor",
        score=score,
        weight=1.0,
        reason="Test factor.",
    )
