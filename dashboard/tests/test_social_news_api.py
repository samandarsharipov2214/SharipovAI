"""Tests for Social News Monitor dashboard API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dashboard import create_app


@pytest.fixture(autouse=True)
def _public_dashboard_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")


def test_social_news_api_returns_truthful_empty_state(monkeypatch, tmp_path: Path) -> None:
    """A fresh store exposes configured sources without inventing news evidence."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())

    response = client.get("/api/social-news")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["sources"]["total"] >= 50
    assert payload["news"]["summary"]["total"] == 0
    assert payload.get("synthetic_fallback_used", False) is False
    assert payload["rss_enabled"] is True
    assert "telegram_client" in payload
    assert "rss_reader" in payload
    assert "agents" in payload
    assert payload["agents"]["supervisor"]["name"] == "Main News Supervisor AI"


def test_social_news_sources_api(monkeypatch, tmp_path: Path) -> None:
    """Sources endpoint should expose configured Telegram/X/RSS definitions and agent configs."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    response = TestClient(create_app()).get("/api/social-news/sources")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "telegram" in payload["grouped"]
    assert "x" in payload["grouped"]
    assert "rss" in payload["grouped"]
    assert "by_category" in payload
    assert "sports" in payload["by_category"]
    assert "weather" in payload["by_category"]
    assert "telegram_client" in payload
    assert "rss_reader" in payload
    assert "agent_configs" in payload


def test_social_news_agents_api(monkeypatch, tmp_path: Path) -> None:
    """Agents endpoint should expose sub-AI and supervisor report."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    response = TestClient(create_app()).get("/api/social-news/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["supervisor"]["agent_count"] >= 8
    assert any(agent["id"] == "sports_news_ai" for agent in payload["agents"])
    assert any(agent["id"] == "weather_news_ai" for agent in payload["agents"])
    assert any(agent["id"] == "telegram_news_ai" for agent in payload["agents"])
    assert any(agent["id"] == "x_news_ai" for agent in payload["agents"])


def test_social_news_supervisor_api(monkeypatch, tmp_path: Path) -> None:
    """Supervisor endpoint should return Main News Supervisor AI assessment."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())
    client.post(
        "/api/social-news/analyze",
        json={"items": [{"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"}]},
    )

    response = client.get("/api/social-news/supervisor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["supervisor"]["name"] == "Main News Supervisor AI"
    assert payload["supervisor"]["decision"] == "BLOCK_BUY_AND_VERIFY"
    assert payload["agents"]


def test_social_news_rss_status_api(monkeypatch, tmp_path: Path) -> None:
    """RSS status endpoint should expose allowlisted RSS sources."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    response = TestClient(create_app()).get("/api/social-news/rss/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["rss_reader"]["enabled"] is True
    assert payload["rss_reader"]["source_count"] >= 1


def test_social_news_rss_refresh_api(monkeypatch, tmp_path: Path) -> None:
    """Fresh RSS evidence is accepted; stale timestamps are not refreshed synthetically."""

    import news_monitor.rss_reader as rss_reader

    def fake_parse(_url: str) -> SimpleNamespace:
        return SimpleNamespace(
            bozo=False,
            entries=[
                SimpleNamespace(
                    title="BTC ETF inflow update",
                    summary="Bitcoin market inflow summary",
                    link="https://example.com/btc",
                    # Keep the fixture fresh for the current CI date. The old
                    # January timestamp correctly became stale by August.
                    published_parsed=(2026, 8, 11, 10, 0, 0, 0, 0, 0),
                )
            ],
        )

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    monkeypatch.setattr(rss_reader.feedparser, "parse", fake_parse)
    client = TestClient(create_app())

    response = client.post("/api/social-news/rss/refresh", json={"limit_per_source": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["items"]
    assert payload["news"]["summary"]["total"] >= 1
    assert payload["agents"]["supervisor"]["agent_count"] >= 8
    assert payload.get("synthetic_fallback_used", False) is False


def test_social_news_telegram_status_when_not_configured(monkeypatch, tmp_path: Path) -> None:
    """Telegram client status should explain missing config without secrets."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING", "TELEGRAM_NEWS_SOURCES"):
        monkeypatch.delenv(name, raising=False)

    response = TestClient(create_app()).get("/api/social-news/telegram/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["telegram_client"]["configured"] is False
    assert "TELEGRAM_SESSION_STRING" in payload["telegram_client"]["missing"]
    assert "api_hash" not in str(payload).lower()
