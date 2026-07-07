"""Deterministic learning engine for decision outcomes.

The learning engine stores and summarizes paper-trade outcomes. It does not
call AI models, APIs, exchanges, or execution systems.
"""

from __future__ import annotations

from datetime import timezone

from memory import DecisionRecord, MemoryEngine

from .exceptions import LearningEngineError
from .models import LearningRecord, LearningSummary
from .statistics import LearningStatistics


class LearningEngine:
    """Records and summarizes decision outcome history."""

    def __init__(
        self,
        memory_engine: MemoryEngine | None = None,
        statistics: LearningStatistics | None = None,
    ) -> None:
        """Initialize the learning engine.

        Args:
            memory_engine: Optional memory engine used for persistent records.
            statistics: Optional statistics calculator.
        """

        self._memory_engine = memory_engine or MemoryEngine()
        self._statistics = statistics or LearningStatistics()
        self._records: list[LearningRecord] = []

    def record(self, record: LearningRecord) -> None:
        """Record a learning outcome.

        Args:
            record: Learning record to store.

        Raises:
            LearningEngineError: If the record is invalid.
        """

        if not isinstance(record, LearningRecord):
            raise LearningEngineError("LearningEngine requires a LearningRecord.")

        self._records.append(record)
        self._memory_engine.save(self._to_decision_record(record))

    def history(self) -> list[LearningRecord]:
        """Return recorded learning history.

        Returns:
            Recorded learning records.
        """

        return list(self._records)

    def summary(self) -> LearningSummary:
        """Return summary statistics for recorded history.

        Returns:
            Learning summary.
        """

        return self._statistics.summarize(self._records)

    def clear(self) -> None:
        """Clear in-memory learning records."""

        self._records.clear()

    def _to_decision_record(self, record: LearningRecord) -> DecisionRecord:
        """Convert a learning record to a memory decision record.

        Args:
            record: Learning record to convert.

        Returns:
            Decision record for memory storage.
        """

        return DecisionRecord(
            id=f"learning-{record.trade.symbol}-{record.trade.timestamp.timestamp()}",
            timestamp=record.trade.timestamp.astimezone(timezone.utc),
            symbol=record.trade.symbol,
            decision=record.decision.decision.value,
            confidence=record.decision.confidence,
            agents=[],
            factor_scores=[],
            reason=record.decision.reason,
            result="SUCCESS" if record.success else "FAILURE",
            profit_loss=record.profit_loss,
            notes="Stored by LearningEngine.",
        )
