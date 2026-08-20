from __future__ import annotations

from typing import Any

import news_monitor.news_autorun as news_autorun


def test_failed_refresh_does_not_advance_success_timestamp(monkeypatch) -> None:
    state: dict[str, Any] = {
        "last_refresh_at": 100,
        "last_refresh_item_count": 3,
        "news": {"items": [{"title": "old but previously verified"}]},
    }

    monkeypatch.setattr(news_autorun.time, "time", lambda: 1_000)
    monkeypatch.setattr(news_autorun, "load_news_state", lambda: state)
    monkeypatch.setattr(news_autorun, "save_news_state", lambda payload: state.update(payload))

    def fail_read(*, limit_per_source: int) -> dict[str, Any]:
        raise RuntimeError(f"rss unavailable for limit={limit_per_source}")

    monkeypatch.setattr(news_autorun, "read_rss_items", fail_read)

    result = news_autorun.refresh_news_now(reason="test_failure")

    assert result["status"] == "error"
    assert state["last_refresh_at"] == 100
    assert state["last_refresh_attempt_at"] == 1_000
    assert state["last_refresh_attempt_reason"] == "test_failure"
    assert state["source_mode"] == "rss_refresh_runtime_error"
    assert result["last_successful_refresh_at"] == 100
    assert result["last_refresh_attempt_at"] == 1_000


def test_failed_attempt_cannot_make_stale_state_fresh(monkeypatch) -> None:
    state: dict[str, Any] = {
        "last_refresh_at": 100,
        "last_refresh_attempt_at": 1_000,
        "last_refresh_errors": [{"source_id": "news_autorun", "error": "RuntimeError: unavailable"}],
        "source_mode": "rss_refresh_runtime_error",
    }
    calls: list[str] = []

    monkeypatch.setattr(news_autorun.time, "time", lambda: 1_001)
    monkeypatch.setattr(news_autorun, "load_news_state", lambda: state)
    monkeypatch.setattr(news_autorun, "news_stale_seconds", lambda: 240)

    def record_refresh(*, reason: str = "manual", limit_per_source: int | None = None) -> dict[str, Any]:
        calls.append(reason)
        return {"status": "error", "reason": reason}

    monkeypatch.setattr(news_autorun, "refresh_news_now", record_refresh)

    result = news_autorun.refresh_news_if_stale(reason="retry_stale_news")

    assert calls == ["retry_stale_news"]
    assert result["status"] == "error"
