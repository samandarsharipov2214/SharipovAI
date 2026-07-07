"""Tests for the deterministic learning engine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from decision import DecisionOutput, DecisionType
from learning_engine import LearningEngine
from memory import MemoryEngine
from paper_trading import PaperTrade


def test_record(tmp_path: Path) -> None:
    """Recording stores a learning record."""

    engine = _engine(tmp_path)
    record = _record(10.0)
    engine.record(record)

    assert engine.history() == [record]


def test_history(tmp_path: Path) -> None:
    """History returns recorded records."""

    engine = _engine(tmp_path)
    first = _record(10.0)
    second = _record(-5.0)
    engine.record(first)
    engine.record(second)

    assert engine.history() == [first, second]


def test_clear(tmp_path: Path) -> None:
    """Clear removes in-memory records."""

    engine = _engine(tmp_path)
    engine.record(_record(10.0))
    engine.clear()

    assert engine.history() == []


def test_summary(tmp_path: Path) -> None:
    """Summary returns deterministic aggregate statistics."""

    engine = _engine(tmp_path)
    engine.record(_record(10.0))
    engine.record(_record(-5.0))
    summary = engine.summary()

    assert summary.total_trades == 2
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.average_profit == 10.0
    assert summary.average_loss == 5.0
    assert summary.best_trade == 10.0
    assert summary.worst_trade == -5.0


def test_win_rate(tmp_path: Path) -> None:
    """Win rate is calculated as wins divided by total trades."""

    engine = _engine(tmp_path)
    engine.record(_record(10.0))
    engine.record(_record(20.0))
    engine.record(_record(-5.0))

    assert engine.summary().win_rate == 66.67


def test_recommendations(tmp_path: Path) -> None:
    """Recommendations are generated from deterministic thresholds."""

    poor = _engine(tmp_path / "poor")
    poor.record(_record(-20.0))
    poor.record(_record(5.0))
    poor.record(_record(-10.0))

    strong = _engine(tmp_path / "strong")
    strong.record(_record(20.0))
    strong.record(_record(15.0))
    strong.record(_record(5.0))

    poor_recommendations = poor.summary().recommendations
    strong_recommendations = strong.summary().recommendations

    assert "Strategy quality is poor." in poor_recommendations
    assert "Losses exceed profits." in poor_recommendations
    assert "More historical data is required." in poor_recommendations
    assert "Current strategy performs well." in strong_recommendations
    assert "More historical data is required." in strong_recommendations


def test_record_is_saved_to_memory(tmp_path: Path) -> None:
    """Learning records are stored through MemoryEngine."""

    memory_engine = MemoryEngine(tmp_path / "memory.json")
    engine = LearningEngine(memory_engine=memory_engine)
    engine.record(_record(10.0))

    records = memory_engine.load_all()
    assert len(records) == 1
    assert records[0].symbol == "BTCUSDT"
    assert records[0].profit_loss == 10.0


def _engine(tmp_path: Path) -> LearningEngine:
    """Create a learning engine with isolated memory."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    return LearningEngine(memory_engine=MemoryEngine(tmp_path / "memory.json"))


def _record(profit_loss: float) -> object:
    """Create a learning record."""

    from learning_engine import LearningRecord

    return LearningRecord(
        trade=PaperTrade(
            symbol="BTCUSDT",
            side="SELL",
            quantity=1.0,
            price=100.0,
            timestamp=datetime.now(timezone.utc),
        ),
        decision=DecisionOutput(
            decision=DecisionType.BUY,
            confidence=80.0,
            reason="Test decision.",
            warnings=[],
        ),
        profit_loss=profit_loss,
        success=profit_loss > 0,
    )
