from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from dashboard.database_api import install_database_api
from dashboard.news_agent_network_api import install_news_agent_network_api
from news_intelligence.agents import SourceAgent
from news_intelligence.hub import NewsHub
from news_intelligence.models import NewsArticle, SourceFetch
from news_intelligence.sources import source_definitions
from storage import ProjectDatabase


def database(tmp_path: Path) -> ProjectDatabase:
    value = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    value.initialize()
    return value


def article(article_id: str, *, title: str = "Market update") -> NewsArticle:
    definition = source_definitions()[0]
    return NewsArticle(
        article_id=article_id,
        title=title,
        source=definition.name,
        category=definition.category,
        published_at="2026-01-01T00:00:00+00:00",
        link=f"https://example.com/{article_id}",
        summary="Verified source report with economic and market impact.",
        language="en",
        source_type=definition.source_type,
    )


def fetched() -> SourceFetch:
    definition = source_definitions()[0]
    return SourceFetch(
        source_id=definition.source_id,
        source_name=definition.name,
        source_type=definition.source_type,
        category=definition.category,
        requested_at_ms=1_000,
        received_at_ms=1_100,
        status_code=200,
        verified=True,
        error="",
        item_count=1,
    )


def agent() -> SourceAgent:
    return SourceAgent(definition=source_definitions()[0])


def test_news_memory_and_events_survive_restart(tmp_path: Path) -> None:
    db = database(tmp_path)
    first = NewsHub(database=db)
    result = first.ingest(agent(), [article("article-1")], fetched())
    assert result.accepted == 1
    first.event("cycle_completed", "done", data={"accepted": 1})
    assert first.state()["database_backed"] is True

    restored = NewsHub(database=db)
    assert restored.state()["article_history_count"] == 1
    assert restored.state()["event_history_count"] == 1
    assert restored.memory()[0]["article"]["article_id"] == "article-1"
    assert restored.events()[0]["type"] == "cycle_completed"


def test_duplicate_article_is_idempotent_but_conflicting_payload_blocks(tmp_path: Path) -> None:
    db = database(tmp_path)
    hub = NewsHub(database=db)
    assert hub.ingest(agent(), [article("same")], fetched()).accepted == 1
    duplicate = hub.ingest(agent(), [article("same")], fetched())
    assert duplicate.accepted == 0
    assert duplicate.duplicates == 1
    with pytest.raises(RuntimeError, match="conflict"):
        hub.ingest(agent(), [article("same", title="Tampered title")], fetched())


def test_database_history_exceeds_bounded_ram_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NEWS_AGENT_MEMORY_LIMIT", "50")
    db = database(tmp_path)
    hub = NewsHub(database=db)
    for index in range(60):
        result = hub.ingest(agent(), [article(f"article-{index}")], fetched())
        assert result.accepted == 1
    state = hub.state()
    assert state["memory_size"] == 50
    assert state["article_history_count"] == 60
    restored = NewsHub(database=db)
    assert restored.state()["memory_size"] == 50
    assert restored.state()["article_history_count"] == 60


def test_corrupt_persisted_envelope_fails_closed(tmp_path: Path) -> None:
    db = database(tmp_path)
    db.put_json("news_memory", "broken", {"article": {}, "fetched": {}}, expected_version=0)
    with pytest.raises((RuntimeError, ValueError)):
        NewsHub(database=db)


def test_dashboard_news_network_uses_same_project_database(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared.db'}")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    app = FastAPI()
    install_database_api(app)
    install_news_agent_network_api(app)
    assert app.state.news_agent_network.database is app.state.project_database
    assert app.state.news_agent_network.hub.database is app.state.project_database
