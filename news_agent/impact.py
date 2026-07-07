"""Deterministic news impact scoring."""

from __future__ import annotations

from data_layer.models import DataItem


class ImpactScorer:
    """Scores news impact using deterministic keyword matching."""

    MAJOR_WORDS: tuple[str, ...] = (
        "ETF",
        "SEC",
        "Hack",
        "Ban",
        "Approval",
        "Fed",
        "Inflation",
        "Rate",
        "Liquidation",
        "Bankruptcy",
    )
    POINTS_PER_MAJOR_WORD: float = 10.0

    def score(self, item: DataItem) -> float:
        """Calculate deterministic impact score for a news item.

        Args:
            item: Data item to score.

        Returns:
            Impact score from 0 to 100.
        """

        text = f"{item.title} {item.content}".upper()
        matches = sum(1 for word in self.MAJOR_WORDS if word.upper() in text)
        return min(matches * self.POINTS_PER_MAJOR_WORD, 100.0)
