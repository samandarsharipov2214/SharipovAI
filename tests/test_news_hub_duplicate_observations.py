from __future__ import annotations

import pytest

from news_intelligence.agents import SourceAgent
from news_intelligence.hub import NewsHub
from news_intelligence.models import NewsArticle, SourceFetch
from news_intelligence.sources import SourceDefinition
from storage import ProjectDatabase


def _agent() -> SourceAgent:
    return SourceAgent(
        definition=SourceDefinition(
            source_id="source",
            name="Source",
            url="https://example.test/feed",
            category="crypto_news",
            trust_score=80,
        )
    )


def _article(*, title: str = "Bitcoin market update") -> NewsArticle:
    return NewsArticle(
        article_id="article-1",
        title=title,
        source="Source",
        category="crypto_news",
        published_at="2026-08-04T20:00:00+00:00",
        link="https://example.test/article-1",
        summary="Verified market update.",
        language="en",
        source_type="rss",
    )


def _fetch(requested: int, received: int) -> SourceFetch:
    return SourceFetch(
        source_id="source",
        source_name="Source",
        source_type="rss",
        category="crypto_news",
        requested_at_ms=requested,
        received_at_ms=received,
        status_code=200,
        verified=True,
        error="",
        item_count=1,
    )


def test_repeat_fetch_timestamps_are_duplicate_not_conflict(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    hub = NewsHub(database=database)

    first = hub.ingest(_agent(), [_article()], _fetch(1_000, 1_100))
    repeated = hub.ingest(_agent(), [_article()], _fetch(2_000, 2_100))

    assert first.accepted == 1
    assert repeated.accepted == 0
    assert repeated.duplicates == 1
    assert len(database.get_json("news_memory", "article-1")["value"]["article"]) > 0


def test_material_article_change_with_same_id_is_conflict(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    hub = NewsHub(database=database)
    hub.ingest(_agent(), [_article()], _fetch(1_000, 1_100))

    with pytest.raises(RuntimeError, match="news article evidence conflict"):
        hub.ingest(
            _agent(),
            [_article(title="Materially changed title")],
            _fetch(2_000, 2_100),
        )
