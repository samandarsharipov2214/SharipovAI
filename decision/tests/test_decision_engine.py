"""Tests for the deterministic decision engine."""

from __future__ import annotations

from analysis import FactorScore
from core.orchestrator import AgentResult
from decision import DecisionEngine, DecisionInput, DecisionType


def test_make_decision_returns_buy_for_positive_majority() -> None:
    """BUY is returned when positive agents have majority and confidence is high."""

    output = DecisionEngine().make_decision(
        DecisionInput(
            agent_results=[
                _agent("market", "BUY"),
                _agent("news", "POSITIVE"),
                _agent("risk", "IGNORE"),
            ],
            factor_scores=[_factor()],
            confidence=80.0,
        )
    )

    assert output.decision is DecisionType.BUY


def test_make_decision_returns_watch_for_neutral_majority() -> None:
    """WATCH is returned when neutral agents have majority."""

    output = DecisionEngine().make_decision(
        DecisionInput(
            agent_results=[
                _agent("market", "WATCH"),
                _agent("news", "NEUTRAL"),
                _agent("risk", "IGNORE"),
            ],
            factor_scores=[_factor()],
            confidence=60.0,
        )
    )

    assert output.decision is DecisionType.WATCH


def test_make_decision_returns_ignore_when_no_rule_matches() -> None:
    """IGNORE is returned when BUY and WATCH conditions are not met."""

    output = DecisionEngine().make_decision(
        DecisionInput(
            agent_results=[
                _agent("market", "BUY"),
                _agent("news", "IGNORE"),
                _agent("risk", "IGNORE"),
            ],
            factor_scores=[_factor()],
            confidence=80.0,
        )
    )

    assert output.decision is DecisionType.IGNORE


def test_make_decision_returns_no_decision() -> None:
    """NO_DECISION is returned below the confidence threshold."""

    output = DecisionEngine().make_decision(
        DecisionInput(
            agent_results=[_agent("market", "BUY")],
            factor_scores=[_factor()],
            confidence=59.99,
        )
    )

    assert output.decision is DecisionType.NO_DECISION


def test_make_decision_low_confidence_reason() -> None:
    """Low confidence produces a clear reason."""

    output = DecisionEngine().make_decision(
        DecisionInput(factor_scores=[_factor()], confidence=10.0)
    )

    assert output.decision is DecisionType.NO_DECISION
    assert "confidence is below" in output.reason


def test_make_decision_high_portfolio_risk() -> None:
    """High portfolio risk returns IGNORE."""

    output = DecisionEngine().make_decision(
        DecisionInput(
            agent_results=[
                _agent("market", "BUY"),
                _agent("news", "BUY"),
                _agent("risk", "BUY"),
            ],
            factor_scores=[_factor()],
            portfolio_risk=80.01,
            confidence=90.0,
        )
    )

    assert output.decision is DecisionType.IGNORE
    assert "portfolio risk" in output.reason


def test_make_decision_failed_agents_warning() -> None:
    """Failed agents are reported as warnings."""

    output = DecisionEngine().make_decision(
        DecisionInput(
            agent_results=[
                _agent("market", "WATCH"),
                AgentResult(
                    agent_name="news",
                    success=False,
                    confidence=0.0,
                    summary="failed",
                    data={},
                ),
            ],
            factor_scores=[_factor()],
            confidence=60.0,
        )
    )

    assert any("news" in warning for warning in output.warnings)


def test_make_decision_no_factor_scores_warning() -> None:
    """Missing factor scores are reported as warnings."""

    output = DecisionEngine().make_decision(
        DecisionInput(agent_results=[_agent("market", "WATCH")], confidence=60.0)
    )

    assert "No factor scores were provided." in output.warnings


def _agent(name: str, summary: str) -> AgentResult:
    """Create a successful agent result for tests."""

    return AgentResult(
        agent_name=name,
        success=True,
        confidence=1.0,
        summary=summary,
        data={},
    )


def _factor() -> FactorScore:
    """Create a factor score for tests."""

    return FactorScore(
        name="Test Factor",
        score=50.0,
        weight=1.0,
        reason="Test factor.",
    )
