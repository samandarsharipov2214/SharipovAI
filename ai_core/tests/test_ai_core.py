"""Tests for the SharipovAI AI Core pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ai_core import AICore, AICoreInput
from analysis import FactorScore
from core.orchestrator import Agent, AgentResult, Orchestrator
from decision import DecisionType
from memory import MemoryEngine
from portfolio_engine import PortfolioInput, Position
from risk_engine import RiskInput


def test_run_no_registered_agents(tmp_path: Path) -> None:
    """Pipeline runs with no registered agents."""

    core = _core(tmp_path)
    output = core.run(_input())

    assert output.agent_results == []
    assert output.consensus.failed_agents == 0
    assert output.decision.decision is DecisionType.NO_DECISION


def test_run_one_successful_agent(tmp_path: Path) -> None:
    """Pipeline runs with one successful agent."""

    orchestrator = Orchestrator()
    orchestrator.register_agent(_StaticAgent("agent", "BUY"))
    output = _core(tmp_path, orchestrator).run(_input())

    assert len(output.agent_results) == 1
    assert output.agent_results[0].success is True
    assert output.consensus.positive_agents == 1


def test_run_multiple_agents(tmp_path: Path) -> None:
    """Pipeline runs with multiple registered agents."""

    orchestrator = Orchestrator()
    orchestrator.register_agent(_StaticAgent("a", "BUY"))
    orchestrator.register_agent(_StaticAgent("b", "POSITIVE"))
    orchestrator.register_agent(_StaticAgent("c", "WATCH"))
    output = _core(tmp_path, orchestrator).run(_input())

    assert len(output.agent_results) == 3
    assert output.consensus.positive_agents == 2
    assert output.decision.decision is DecisionType.BUY


def test_run_failed_agent(tmp_path: Path) -> None:
    """Failed agents are included in consensus and confidence."""

    orchestrator = Orchestrator()
    orchestrator.register_agent(_StaticAgent("a", "BUY"))
    orchestrator.register_agent(_FailingAgent("b"))
    output = _core(tmp_path, orchestrator).run(_input())

    assert len(output.agent_results) == 2
    assert output.consensus.failed_agents == 1
    assert any("Failed agents" in warning for warning in output.confidence.warnings)


def test_run_decision_stored_in_memory(tmp_path: Path) -> None:
    """Final decision is stored through MemoryEngine."""

    memory_engine = MemoryEngine(tmp_path / "memory.json")
    orchestrator = Orchestrator()
    orchestrator.register_agent(_StaticAgent("a", "BUY"))
    core = AICore(orchestrator=orchestrator, memory_engine=memory_engine)

    output = core.run(_input())
    records = memory_engine.load_all()

    assert len(records) == 1
    assert records[0].decision == output.decision.decision.value
    assert records[0].symbol == "BTCUSDT"


def test_run_complete_pipeline(tmp_path: Path) -> None:
    """Complete pipeline returns every output component."""

    orchestrator = Orchestrator()
    orchestrator.register_agent(_StaticAgent("market", "BUY"))
    output = _core(tmp_path, orchestrator).run(_input())

    assert output.agent_results
    assert output.consensus.agreement == 100.0
    assert output.confidence.confidence >= 80.0
    assert output.portfolio.total_value > 0
    assert output.risk.risk_score < 30
    assert output.decision.decision is DecisionType.BUY


class _StaticAgent(Agent):
    """Deterministic successful test agent."""

    def __init__(self, agent_name: str, summary: str) -> None:
        """Initialize the test agent."""

        self._agent_name = agent_name
        self._summary = summary

    def name(self) -> str:
        """Return agent name."""

        return self._agent_name

    def run(self, context: Mapping[str, Any]) -> AgentResult:
        """Return a deterministic successful agent result."""

        return AgentResult(
            agent_name=self._agent_name,
            success=True,
            confidence=100.0,
            summary=self._summary,
            data={
                "top_symbol": "BTCUSDT",
                "factor_scores": [
                    {
                        "name": "Test Factor",
                        "score": 100.0,
                        "weight": 1.0,
                        "reason": "Test factor.",
                    }
                ],
            },
        )


class _FailingAgent(Agent):
    """Deterministic failing test agent."""

    def __init__(self, agent_name: str) -> None:
        """Initialize the test agent."""

        self._agent_name = agent_name

    def name(self) -> str:
        """Return agent name."""

        return self._agent_name

    def run(self, context: Mapping[str, Any]) -> AgentResult:
        """Raise an expected failure for orchestrator isolation."""

        raise RuntimeError("agent failed")


def _core(tmp_path: Path, orchestrator: Orchestrator | None = None) -> AICore:
    """Create an AI Core with isolated memory."""

    return AICore(
        orchestrator=orchestrator or Orchestrator(),
        memory_engine=MemoryEngine(tmp_path / "memory.json"),
    )


def _input() -> AICoreInput:
    """Create deterministic AI Core input."""

    return AICoreInput(
        context={"symbol": "BTCUSDT", "data_quality": 100.0},
        portfolio=PortfolioInput(
            cash=1000.0,
            positions=[
                Position(
                    symbol="BTCUSDT",
                    quantity=0.01,
                    average_price=50000.0,
                    current_price=50000.0,
                )
            ],
        ),
        risk=RiskInput(
            portfolio_drawdown=1.0,
            portfolio_exposure=10.0,
            asset_exposure=5.0,
            volatility_score=10.0,
            liquidity_score=90.0,
            correlation_score=10.0,
        ),
    )
