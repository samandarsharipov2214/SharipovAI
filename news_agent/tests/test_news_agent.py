"""Tests for the deterministic News Agent package."""

from __future__ import annotations

from data_layer import DataItem
from data_layer.providers import RSSProvider
from news_agent import ImpactScorer, NewsAgent, NewsClassifier


def test_classification() -> None:
    """Classifier assigns expected category."""

    item = _item("Bitcoin ETF approval", "Bitcoin market sees ETF approval.")

    assert NewsClassifier().category(item) == "Bitcoin"


def test_sentiment() -> None:
    """Classifier assigns expected sentiment."""

    bullish = _item("Ethereum rally", "Ethereum growth and bullish inflow.")
    bearish = _item("Exchange hack", "Hack causes loss and bearish outflow.")
    neutral = _item("Market update", "Daily market note.")

    classifier = NewsClassifier()
    assert classifier.sentiment(bullish) == "Bullish"
    assert classifier.sentiment(bearish) == "Bearish"
    assert classifier.sentiment(neutral) == "Neutral"


def test_impact_score() -> None:
    """Impact scorer counts major words."""

    item = _item("SEC ETF Approval", "Fed rate inflation update.")

    assert ImpactScorer().score(item) == 60.0


def test_empty_feed() -> None:
    """Empty feed returns successful empty analysis."""

    result = NewsAgent(RSSProvider(items=[])).run({})

    assert result.success is True
    assert result.summary == "Processed 0 news items."
    assert result.data["analyses"] == []
    assert result.data["average_impact"] == 0.0
    assert result.data["highest_impact"] == 0.0


def test_multiple_news() -> None:
    """Multiple news items are processed."""

    result = NewsAgent(RSSProvider(items=_items())).run({})

    assert result.summary == "Processed 3 news items."
    assert len(result.data["analyses"]) == 3
    assert "Bitcoin" in result.data["categories"]
    assert "Security" in result.data["categories"]


def test_agent_result() -> None:
    """News Agent returns expected AgentResult data."""

    result = NewsAgent(RSSProvider(items=_items())).run({})

    assert result.agent_name == "News Agent"
    assert result.success is True
    assert "analyses" in result.data
    assert "average_impact" in result.data
    assert "highest_impact" in result.data
    assert "categories" in result.data


def _items() -> list[DataItem]:
    """Create deterministic news fixtures."""

    return [
        _item("Bitcoin ETF Approval", "Bitcoin ETF approval is bullish."),
        _item("Exchange hack", "Major exchange hack causes loss."),
        _item("Fed rate update", "Fed discusses inflation and rate policy."),
    ]


def _item(title: str, content: str) -> DataItem:
    """Create a data item fixture."""

    return DataItem(
        source="rss",
        category="news",
        title=title,
        content=content,
        url=None,
        published_at=None,
        metadata={},
    )
