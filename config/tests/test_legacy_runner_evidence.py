from __future__ import annotations

from memory import MemoryEngine
from paper_trading import PaperEngine
from runner import SharipovAIRunner


def test_legacy_runner_does_not_persist_memory_trade_or_learning(tmp_path) -> None:
    memory = MemoryEngine(tmp_path / "legacy-memory.json")
    paper = PaperEngine()
    runner = SharipovAIRunner(memory_engine=memory, paper_engine=paper)

    output = runner.run()

    assert output.decision == "NO_DECISION"
    assert output.confidence == 0.0
    assert output.open_positions == 0
    assert output.paper_pnl == 0.0
    assert output.learning_summary.total_trades == 0
    assert memory.load_all() == []
    assert paper.positions() == []
    assert "LEGACY_OFFLINE_DIAGNOSTIC" in output.report
