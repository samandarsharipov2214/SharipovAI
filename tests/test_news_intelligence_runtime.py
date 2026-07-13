from __future__ import annotations

from news_intelligence.agents import SourceAgent
from news_intelligence.models import NewsArticle, SourceFetch
from news_intelligence.network import NewsAgentNetwork
from news_intelligence.sources import SourceDefinition


def _definition() -> SourceDefinition:
    return SourceDefinition(
        source_id="test_feed",
        name="Test Feed",
        url="https://example.com/feed.xml",
        category="crypto_news",
        trust_score=90,
    )


def _article() -> NewsArticle:
    return NewsArticle(
        article_id="article-1",
        title="Bitcoin ETF approval supports market inflow",
        source="Test Feed",
        category="crypto_news",
        published_at="2026-07-13T00:00:00+00:00",
        link="https://example.com/article-1",
        summary="Verified market adoption update.",
        language="en",
        source_type="rss",
    )


def _fetch() -> SourceFetch:
    return SourceFetch(
        source_id="test_feed",
        source_name="Test Feed",
        source_type="rss",
        category="crypto_news",
        requested_at_ms=1_000,
        received_at_ms=1_001,
        status_code=200,
        verified=True,
        error="",
        item_count=1,
    )


def test_source_agent_registers_real_article_and_deduplicates() -> None:
    agent = SourceAgent(definition=_definition())
    first = agent.register(_article(), _fetch())
    duplicate = agent.register(_article(), _fetch())

    assert first is not None
    assert first.article.article_id == "article-1"
    assert first.fetched.verified is True
    assert first.impact == "bullish"
    assert duplicate is None
    assert agent.status()["accepted"] == 1
    assert agent.status()["duplicates"] == 1
    assert agent.status()["synthetic_fallback_used"] is False


def test_news_network_constructs_with_injected_collector() -> None:
    definition = _definition()

    class Collector:
        definitions = [definition]

        def collect(self, selected: SourceDefinition):
            assert selected.source_id == definition.source_id
            return [_article()], _fetch()

    network = NewsAgentNetwork(collector=Collector())
    # The runtime definitions come from the canonical registry, while the
    # collector is injectable for deterministic tests.  Construction itself
    # must never require a network call.
    assert network.snapshot()["status"] == "stopped"
