from __future__ import annotations

import pytest

from news_intelligence import NewsArticle, NewsHub, SourceAgent, SourceDefinition, SourceFetch
from storage import ProjectDatabase


def _fetch() -> SourceFetch:
    return SourceFetch(
        source_id="test-feed",
        source_name="Test Feed",
        source_type="rss",
        category="markets",
        requested_at_ms=1,
        received_at_ms=2,
        status_code=200,
        verified=True,
        error="",
        item_count=1,
    )


def _article(title: str) -> NewsArticle:
    return NewsArticle(
        article_id="article-1",
        title=title,
        source="Test Feed",
        category="markets",
        published_at="2026-08-11T10:00:00+00:00",
        link="https://example.test/article-1",
        summary="market update",
        language="en",
        source_type="rss",
    )


def test_duplicate_news_identity_is_idempotent_but_conflict_fails_closed(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    database.initialize()
    hub = NewsHub(database=database)
    agent = SourceAgent(
        definition=SourceDefinition(
            source_id="test-feed",
            name="Test Feed",
            url="https://example.test/rss",
            category="markets",
            trust_score=90,
        )
    )

    first = hub.ingest(agent, [_article("Original title")], _fetch())
    duplicate = hub.ingest(agent, [_article("Original title")], _fetch())

    assert first.accepted == 1
    assert duplicate.duplicates == 1

    with pytest.raises(RuntimeError, match="evidence conflict"):
        hub.ingest(agent, [_article("Conflicting title")], _fetch())
