"""Tests for the deterministic consensus engine."""

from __future__ import annotations

import pytest

from consensus import (
    ConsensusEngine,
    ConsensusEngineError,
    ConsensusInput,
    ConsensusLevel,
)
from core.orchestrator import AgentResult


def test_evaluate_unanimous_positive_consensus() -> None:
    """All successful agents agreeing creates unanimous consensus."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                _agent("market", "BUY"),
                _agent("news", "POSITIVE"),
                _agent("risk", "BULLISH"),
            ]
        )
    )

    assert output.level is ConsensusLevel.UNANIMOUS
    assert output.agreement == 100.0
    assert output.positive_agents == 3
    assert output.negative_agents == 0
    assert output.neutral_agents == 0
    assert output.failed_agents == 0


def test_evaluate_strong_consensus() -> None:
    """Three of four agents agreeing creates strong consensus."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                _agent("a", "BUY"),
                _agent("b", "POSITIVE"),
                _agent("c", "BULLISH"),
                _agent("d", "WATCH"),
            ]
        )
    )

    assert output.level is ConsensusLevel.STRONG
    assert output.agreement == 75.0


def test_evaluate_moderate_consensus() -> None:
    """Three of five agents agreeing creates moderate consensus."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                _agent("a", "SELL"),
                _agent("b", "NEGATIVE"),
                _agent("c", "BEARISH"),
                _agent("d", "WATCH"),
                _agent("e", "BUY"),
            ]
        )
    )

    assert output.level is ConsensusLevel.MODERATE
    assert output.agreement == 60.0
    assert output.negative_agents == 3


def test_evaluate_weak_consensus() -> None:
    """Four of seven agents agreeing creates weak consensus."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                _agent("a", "WATCH"),
                _agent("b", "NEUTRAL"),
                _agent("c", "WATCH"),
                _agent("d", "NO_DECISION"),
                _agent("e", "BUY"),
                _agent("f", "SELL"),
                _agent("g", "IGNORE"),
            ]
        )
    )

    assert output.level is ConsensusLevel.WEAK
    assert output.agreement == 57.14
    assert output.neutral_agents == 4


def test_evaluate_conflict_consensus() -> None:
    """Evenly split successful agents create conflict."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                _agent("a", "BUY"),
                _agent("b", "SELL"),
            ]
        )
    )

    assert output.level is ConsensusLevel.CONFLICT
    assert output.agreement == 50.0


def test_evaluate_failed_agents_are_counted() -> None:
    """Failed agents are counted separately from successful classifications."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                _agent("a", "BUY"),
                _failed_agent("b"),
                _failed_agent("c"),
            ]
        )
    )

    assert output.level is ConsensusLevel.UNANIMOUS
    assert output.agreement == 100.0
    assert output.failed_agents == 2


def test_evaluate_no_successful_agents_returns_conflict() -> None:
    """No successful agents is an analytical conflict outcome."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(agent_results=[_failed_agent("a")])
    )

    assert output.level is ConsensusLevel.CONFLICT
    assert output.agreement == 0.0
    assert "no successful agent results" in output.summary


def test_evaluate_data_labels_are_classified() -> None:
    """Classification labels can be read from structured result data."""

    output = ConsensusEngine().evaluate(
        ConsensusInput(
            agent_results=[
                AgentResult("a", True, 1.0, "result", {"signal": "BUY"}),
                AgentResult("b", True, 1.0, "result", {"signal": "SELL"}),
                AgentResult("c", True, 1.0, "result", {"signal": "SELL"}),
            ]
        )
    )

    assert output.level is ConsensusLevel.MODERATE
    assert output.negative_agents == 2


def test_evaluate_invalid_input_raises_error() -> None:
    """Invalid infrastructure input raises ConsensusEngineError."""

    with pytest.raises(ConsensusEngineError):
        ConsensusEngine().evaluate(None)  # type: ignore[arg-type]


def _agent(name: str, summary: str) -> AgentResult:
    """Create a successful agent result."""

    return AgentResult(
        agent_name=name,
        success=True,
        confidence=1.0,
        summary=summary,
        data={},
    )


def _failed_agent(name: str) -> AgentResult:
    """Create a failed agent result."""

    return AgentResult(
        agent_name=name,
        success=False,
        confidence=0.0,
        summary="failed",
        data={},
    )
