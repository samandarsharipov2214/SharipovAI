from __future__ import annotations

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


def _article() -> NewsArticle:
    return NewsArticle(
        article_id="article-1",
        title="Bitcoin market update",
        source="Source",
        category="crypto_news",
        published_at="2026-08-06T20:00:00+00:00",
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


def test_article_identity_and_unchanged_fetch_observation_are_separate(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    hub = NewsHub(database=database)

    hub.ingest(_agent(), [_article()], _fetch(1_000, 1_100))
    hub.ingest(_agent(), [_article()], _fetch(2_000, 2_100))

    article = database.get_json("news_article_evidence", "article-1")
    assert article is not None
    assert article["value"] == _article().to_dict()
    assert "fetched" not in article["value"]

    observations = hub.fetch_observations(article_id="article-1")
    # Retrieval timestamps alone are operational telemetry, not independent
    # article provenance.  Repeating an unchanged poll must not grow SQLite
    # linearly; verification/status/error changes remain append-only evidence.
    assert len(observations) == 1
    assert observations[0]["payload"]["fetch"]["received_at_ms"] == 1_100
    assert all(row["entity_type"] == "source_fetch" for row in observations)
    assert hub.state()["article_fetch_evidence_separated"] is True


def test_duplicate_suppressed_by_source_agent_does_not_amplify_unchanged_telemetry(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    hub = NewsHub(database=database)
    agent = _agent()

    first = hub.ingest(agent, [_article()], _fetch(1_000, 1_100))
    duplicate = hub.ingest(agent, [_article()], _fetch(2_000, 2_100))

    assert first.accepted == 1
    assert duplicate.accepted == 0
    assert duplicate.duplicates == 1
    assert len(hub.fetch_observations(article_id="article-1")) == 1
