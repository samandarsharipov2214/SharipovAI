from __future__ import annotations

from typing import Any

import news_monitor.news_autorun as news_autorun


def test_all_source_failure_does_not_replace_or_freshen_saved_news(monkeypatch) -> None:
    old_news = {"items": [{"title": "previous verified item"}]}
    state: dict[str, Any] = {
        "last_refresh_at": 100,
        "last_refresh_item_count": 1,
        "news": old_news,
    }

    monkeypatch.setattr(news_autorun.time, "time", lambda: 1_000)
    monkeypatch.setattr(news_autorun, "load_news_state", lambda: state)
    monkeypatch.setattr(news_autorun, "save_news_state", lambda payload: state.update(payload))
    monkeypatch.setattr(
        news_autorun,
        "read_rss_items",
        lambda *, limit_per_source: {
            "items": [],
            "rss": {"enabled": True},
            "diagnostics": {"working_sources": 0},
            "errors": [{"source_id": "source-a", "error": "timeout"}],
        },
    )

    result = news_autorun.refresh_news_now(reason="all_sources_failed")

    assert result["status"] == "error"
    assert result["error"] == "rss_unavailable_no_verified_source"
    assert result["last_successful_refresh_at"] == 100
    assert state["last_refresh_at"] == 100
    assert state["last_refresh_attempt_at"] == 1_000
    assert state["last_refresh_attempt_reason"] == "all_sources_failed"
    assert state["source_mode"] == "rss_unavailable_no_verified_source"
    assert state["news"] == old_news


def test_verified_empty_feed_is_a_successful_fresh_refresh(monkeypatch) -> None:
    state: dict[str, Any] = {
        "last_refresh_at": 100,
        "news": {"items": [{"title": "old"}]},
    }

    monkeypatch.setattr(news_autorun.time, "time", lambda: 2_000)
    monkeypatch.setattr(news_autorun, "load_news_state", lambda: state)
    monkeypatch.setattr(news_autorun, "save_news_state", lambda payload: state.update(payload))
    monkeypatch.setattr(news_autorun, "analyzed_news_payload", lambda items: {"items": list(items)})
    monkeypatch.setattr(news_autorun, "run_news_agents", lambda items: {"count": len(items)})
    monkeypatch.setattr(
        news_autorun,
        "read_rss_items",
        lambda *, limit_per_source: {
            "items": [],
            "rss": {"enabled": True},
            "diagnostics": {"working_sources": 1},
            "errors": [],
        },
    )

    result = news_autorun.refresh_news_now(reason="verified_empty")

    assert result["status"] == "empty"
    assert state["last_refresh_at"] == 2_000
    assert state["last_refresh_item_count"] == 0
    assert state["source_mode"] == "rss_verified_empty"
    assert state["news"] == {"items": []}
