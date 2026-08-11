from __future__ import annotations

from news_intelligence.agents import SourceAgent
from news_intelligence.hub import NewsHub
from news_intelligence.models import NewsArticle, SourceFetch
from news_intelligence.sources import SourceDefinition
from storage import ProjectDatabase


def _article() -> NewsArticle:
    return NewsArticle(
        article_id="article-1",
        title="Bitcoin market update",
        source="Example",
        category="crypto",
        published_at="2026-08-11T00:00:00+00:00",
        link="https://example.invalid/article-1",
        summary="Bitcoin market update",
        language="en",
        source_type="rss",
    )


def _fetch(*, received_at_ms: int, verified: bool = True, status_code: int = 200, error: str = "") -> SourceFetch:
    return SourceFetch(
        source_id="source-1",
        source_name="Example",
        source_type="rss",
        category="crypto",
        requested_at_ms=max(received_at_ms - 1, 1),
        received_at_ms=received_at_ms,
        status_code=status_code,
        verified=verified,
        error=error,
        item_count=1,
    )


def _agent() -> SourceAgent:
    return SourceAgent(
        definition=SourceDefinition(
            source_id="source-1",
            name="Example",
            url="https://example.invalid/feed",
            category="crypto",
            trust_score=80,
        )
    )


def test_repeated_unchanged_fetch_observation_is_throttled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEWS_FETCH_OBSERVATION_MIN_INTERVAL_SECONDS", "60")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    hub = NewsHub(database=database)
    agent = _agent()
    article = _article()

    hub.ingest(agent, [article], _fetch(received_at_ms=100_000))
    hub.ingest(agent, [article], _fetch(received_at_ms=101_000))

    observations = hub.fetch_observations(article_id=article.article_id, limit=100)
    assert len(observations) == 1
    assert observations[0]["payload"]["fetch"]["status_code"] == 200


def test_fetch_state_change_is_persisted_immediately(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEWS_FETCH_OBSERVATION_MIN_INTERVAL_SECONDS", "60")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    hub = NewsHub(database=database)
    agent = _agent()
    article = _article()

    hub.ingest(agent, [article], _fetch(received_at_ms=100_000))
    hub.ingest(
        agent,
        [article],
        _fetch(received_at_ms=101_000, verified=False, status_code=503, error="upstream unavailable"),
    )

    observations = hub.fetch_observations(article_id=article.article_id, limit=100)
    assert len(observations) == 2
    statuses = [row["payload"]["fetch"]["status_code"] for row in observations]
    assert statuses == [503, 200]


def test_unchanged_fetch_is_reemitted_after_retention_interval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEWS_FETCH_OBSERVATION_MIN_INTERVAL_SECONDS", "60")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    hub = NewsHub(database=database)
    agent = _agent()
    article = _article()

    hub.ingest(agent, [article], _fetch(received_at_ms=100_000))
    hub.ingest(agent, [article], _fetch(received_at_ms=161_000))

    observations = hub.fetch_observations(article_id=article.article_id, limit=100)
    assert len(observations) == 2
    assert observations[0]["created_at_ms"] == 161_000
    assert observations[1]["created_at_ms"] == 100_000


def test_repeated_poll_load_does_not_scale_database_events_linearly(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEWS_FETCH_OBSERVATION_MIN_INTERVAL_SECONDS", "3600")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    hub = NewsHub(database=database)
    agent = _agent()
    article = _article()

    for index in range(500):
        hub.ingest(agent, [article], _fetch(received_at_ms=100_000 + index * 1_000))

    observations = hub.fetch_observations(article_id=article.article_id, limit=1000)
    assert len(observations) == 1
    assert len(database.list_events("news_fetch_observations", limit=1000)) == 1
