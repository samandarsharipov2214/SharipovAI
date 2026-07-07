"""Tests for the SharipovAI runner."""

from __future__ import annotations

from pathlib import Path

from memory import MemoryEngine
from paper_trading import PaperEngine
from runner import RunnerOutput, SharipovAIRunner


def test_runner_executes(tmp_path: Path) -> None:
    """Runner executes and returns output."""

    output = _runner(tmp_path).run()

    assert isinstance(output, RunnerOutput)
    assert output.decision


def test_market_agent_is_used(tmp_path: Path) -> None:
    """Runner registers Market Agent."""

    runner = _runner(tmp_path)
    runner.run()

    assert runner.last_orchestrator is not None
    assert "Market Agent" in runner.last_orchestrator.list_agents()


def test_news_agent_is_used(tmp_path: Path) -> None:
    """Runner registers News Agent."""

    runner = _runner(tmp_path)
    runner.run()

    assert runner.last_orchestrator is not None
    assert "News Agent" in runner.last_orchestrator.list_agents()


def test_paper_account_exists(tmp_path: Path) -> None:
    """Runner creates and returns paper account state."""

    output = _runner(tmp_path).run()

    assert output.paper_cash >= 0
    assert output.paper_equity > 0


def test_learning_summary_exists(tmp_path: Path) -> None:
    """Runner records a learning summary."""

    output = _runner(tmp_path).run()

    assert output.learning_summary.total_trades == 1


def test_report_is_generated(tmp_path: Path) -> None:
    """Runner generates a report."""

    output = _runner(tmp_path).run()

    assert "SharipovAI runner completed." in output.report
    assert "Decision:" in output.report


def test_no_real_api_calls(tmp_path: Path) -> None:
    """Runner uses static data and no external API calls."""

    output = _runner(tmp_path).run()

    assert output.report
    assert output.portfolio_value > 0


def _runner(tmp_path: Path) -> SharipovAIRunner:
    """Create a runner with isolated memory."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    memory_engine = MemoryEngine(tmp_path / "memory.json")
    return SharipovAIRunner(
        memory_engine=memory_engine,
        paper_engine=PaperEngine(),
    )
