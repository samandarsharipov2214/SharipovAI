"""News Agent implementation.

The News Agent processes static data from an RSS provider. It performs no
network calls, AI model calls, exchange execution, or trading execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.orchestrator import Agent, AgentResult
from data_layer.providers import RSSProvider

from .classifier import NewsClassifier
from .models import NewsAnalysis


class NewsAgent(Agent):
    """Deterministic news analysis agent."""

    AGENT_NAME: str = "News Agent"

    def __init__(
        self,
        provider: RSSProvider,
        classifier: NewsClassifier | None = None,
    ) -> None:
        """Initialize the News Agent.

        Args:
            provider: RSS provider used to fetch static news items.
            classifier: Optional deterministic classifier dependency.
        """

        self._provider = provider
        self._classifier = classifier or NewsClassifier()

    def name(self) -> str:
        """Return the agent name."""

        return self.AGENT_NAME

    def run(self, context: Mapping[str, Any]) -> AgentResult:
        """Run deterministic news analysis.

        Args:
            context: Execution context. The current implementation does not
                require context fields.

        Returns:
            Agent result containing news analyses.
        """

        batch = self._provider.fetch()
        analyses = [self._analyze_item(item) for item in batch.items]
        average_impact = _average([analysis.impact_score for analysis in analyses])
        highest_impact = max((analysis.impact_score for analysis in analyses), default=0.0)
        categories = sorted({analysis.category for analysis in analyses})

        return AgentResult(
            agent_name=self.AGENT_NAME,
            success=True,
            confidence=average_impact,
            summary=f"Processed {len(analyses)} news items.",
            data={
                "analyses": [
                    {
                        "headline": analysis.headline,
                        "category": analysis.category,
                        "sentiment": analysis.sentiment,
                        "impact_score": analysis.impact_score,
                        "reason": analysis.reason,
                    }
                    for analysis in analyses
                ],
                "average_impact": average_impact,
                "highest_impact": highest_impact,
                "categories": categories,
            },
        )

    def _analyze_item(self, item: Any) -> NewsAnalysis:
        """Analyze one data item.

        Args:
            item: Data item to analyze.

        Returns:
            Structured news analysis.
        """

        classification = self._classifier.classify(item)
        return NewsAnalysis(
            headline=item.title,
            category=classification.category,
            sentiment=classification.sentiment,
            impact_score=classification.impact_score,
            reason=(
                f"Classified as {classification.category} with "
                f"{classification.sentiment} sentiment using deterministic "
                "keyword rules."
            ),
        )


def _average(values: list[float]) -> float:
    """Calculate an average safely."""

    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)
