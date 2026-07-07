"""Deterministic consensus engine.

This module evaluates agreement across typed agent results only. It does not
include AI behavior, API calls, exchange logic, trading execution, or business
logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.orchestrator import AgentResult

from .exceptions import ConsensusEngineError
from .models import ConsensusInput, ConsensusLevel, ConsensusOutput


@dataclass(frozen=True, slots=True)
class _ConsensusCounts:
    """Internal classification counts."""

    positive: int
    negative: int
    neutral: int
    failed: int

    @property
    def successful(self) -> int:
        """Return the number of successful classified agents."""

        return self.positive + self.negative + self.neutral

    @property
    def dominant_count(self) -> int:
        """Return the largest successful classification count."""

        return max(self.positive, self.negative, self.neutral)

    @property
    def dominant_label(self) -> str:
        """Return the dominant successful classification label."""

        if self.positive >= self.negative and self.positive >= self.neutral:
            return "positive"
        if self.negative >= self.positive and self.negative >= self.neutral:
            return "negative"
        return "neutral"


class ConsensusEngine:
    """Evaluates deterministic consensus across agent results."""

    UNANIMOUS_AGREEMENT: float = 100.0
    STRONG_AGREEMENT: float = 75.0
    MODERATE_AGREEMENT: float = 60.0
    WEAK_AGREEMENT: float = 50.0

    def evaluate(self, input: ConsensusInput) -> ConsensusOutput:
        """Evaluate consensus across agent results.

        Normal analytical outcomes, including conflict or missing successful
        agents, are returned as ``ConsensusOutput`` values.

        Args:
            input: Typed consensus input.

        Returns:
            Consensus evaluation output.

        Raises:
            ConsensusEngineError: If the input object is invalid.
        """

        self._validate_input(input)
        counts = self._count_agents(input.agent_results)
        agreement = self._calculate_agreement(counts)
        level = self._determine_level(counts, agreement)
        summary = self._generate_summary(counts, agreement, level)

        return ConsensusOutput(
            level=level,
            agreement=agreement,
            positive_agents=counts.positive,
            negative_agents=counts.negative,
            neutral_agents=counts.neutral,
            failed_agents=counts.failed,
            summary=summary,
        )

    def _validate_input(self, input: ConsensusInput) -> None:
        """Validate consensus input structure.

        Args:
            input: Candidate consensus input.

        Raises:
            ConsensusEngineError: If the input object is invalid.
        """

        if not isinstance(input, ConsensusInput):
            raise ConsensusEngineError(
                "ConsensusEngine requires a ConsensusInput instance."
            )

    def _count_agents(self, agent_results: list[AgentResult]) -> _ConsensusCounts:
        """Count agent classifications.

        Args:
            agent_results: Agent results to classify.

        Returns:
            Classification counts.
        """

        positive = 0
        negative = 0
        neutral = 0
        failed = 0

        for result in agent_results:
            if not result.success:
                failed += 1
            elif _is_positive(result):
                positive += 1
            elif _is_negative(result):
                negative += 1
            else:
                neutral += 1

        return _ConsensusCounts(
            positive=positive,
            negative=negative,
            neutral=neutral,
            failed=failed,
        )

    def _calculate_agreement(self, counts: _ConsensusCounts) -> float:
        """Calculate agreement score.

        Args:
            counts: Classification counts.

        Returns:
            Agreement score from 0 to 100.
        """

        if counts.successful == 0:
            return 0.0

        return round((counts.dominant_count / counts.successful) * 100.0, 2)

    def _determine_level(
        self,
        counts: _ConsensusCounts,
        agreement: float,
    ) -> ConsensusLevel:
        """Determine consensus level.

        Args:
            counts: Classification counts.
            agreement: Agreement score.

        Returns:
            Consensus level.
        """

        if counts.successful == 0:
            return ConsensusLevel.CONFLICT

        if agreement == self.UNANIMOUS_AGREEMENT:
            return ConsensusLevel.UNANIMOUS

        if agreement >= self.STRONG_AGREEMENT:
            return ConsensusLevel.STRONG

        if agreement >= self.MODERATE_AGREEMENT:
            return ConsensusLevel.MODERATE

        if agreement > self.WEAK_AGREEMENT:
            return ConsensusLevel.WEAK

        return ConsensusLevel.CONFLICT

    def _generate_summary(
        self,
        counts: _ConsensusCounts,
        agreement: float,
        level: ConsensusLevel,
    ) -> str:
        """Generate a human-readable consensus summary.

        Args:
            counts: Classification counts.
            agreement: Agreement score.
            level: Consensus level.

        Returns:
            Human-readable summary.
        """

        if counts.successful == 0:
            return (
                "Consensus is CONFLICT because no successful agent results "
                f"were available. Failed agents: {counts.failed}."
            )

        return (
            f"Consensus is {level.value} with {agreement:.2f}% agreement. "
            f"Dominant view is {counts.dominant_label}. "
            f"Counts: positive={counts.positive}, negative={counts.negative}, "
            f"neutral={counts.neutral}, failed={counts.failed}."
        )


def _is_positive(result: AgentResult) -> bool:
    """Return whether an agent result is positive."""

    return _contains_label(result, {"BUY", "POSITIVE", "BULLISH"})


def _is_negative(result: AgentResult) -> bool:
    """Return whether an agent result is negative."""

    return _contains_label(result, {"SELL", "IGNORE", "NEGATIVE", "BEARISH"})


def _contains_label(result: AgentResult, labels: set[str]) -> bool:
    """Check whether an agent result contains any classification label.

    Args:
        result: Agent result to inspect.
        labels: Uppercase labels to search for.

    Returns:
        ``True`` when any label is present.
    """

    values = [
        result.summary,
        _stringify_mapping(result.data),
    ]
    normalized_text = " ".join(values).upper()
    return any(label in normalized_text for label in labels)


def _stringify_mapping(value: Mapping[str, Any]) -> str:
    """Convert a mapping into searchable text.

    Args:
        value: Mapping to stringify.

    Returns:
        Searchable string representation.
    """

    return " ".join(str(item) for pair in value.items() for item in pair)
