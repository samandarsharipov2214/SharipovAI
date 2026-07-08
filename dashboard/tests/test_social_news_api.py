"""Tests for Social News Monitor dashboard API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dashboard import create_app


def test_social_news_api_returns_seeded_state(monkeypatch, tmp_path: Path) -> None:
    """Social news API should return sources and analyzed news."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())

    response = client.get("/api/social-news")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["sources"]["total"] >= 10
    assert payload["news"]["summary"]["total"] > 0
    assert payload["rss_enabled"] is True
    assert "telegram_client" in payload
    assert "rss_reader" in payload


def test_social_news_sources_api(monkeypatch, tmp_path: Path) -> None:
    """Sources endpoint should expose configured Telegram/X/RSS definitions."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    response = TestClient(create_app()).get("/api/social-news/sources")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "telegram" in payload["grouped"]
    assert "x" in payload["grouped"]
    assert "rss" in payload["grouped"]
    assert "telegram_client" in payload
    assert "rss_reader" in payload


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
    """RSS refresh endpoint should read and analyze RSS items."""

    import news_monitor.rss_reader as rss_reader

    def fake_parse(_url: str) -> SimpleNamespace:
        return SimpleNamespace(
            bozo=False,
            entries=[
                SimpleNamespace(
                    title="BTC ETF inflow update",
                    summary="Bitcoin market inflow summary",
                    link="https://example.com/btc",
                    published_parsed=(2026, 1, 2, 3, 4, 5, 0, 0, 0),
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


def test_social_news_telegram_refresh_disabled_when_not_configured(monkeypatch, tmp_path: Path) -> None:
    """Telegram refresh should not crash when credentials are absent."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    monkeypatch.delenv("TELEGRAM_CLIENT_ENABLED", raising=False)
    client = TestClient(create_app())

    response = client.post("/api/social-news/telegram/refresh", json={"limit_per_source": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["items"] == []
    assert "news" in payload


def test_social_news_analyze_api_blocks_unconfirmed_social_claim(monkeypatch, tmp_path: Path) -> None:
    """Analyze endpoint should flag unconfirmed social posts before trading."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())

    response = client.post(
        "/api/social-news/analyze",
        json={"items": [{"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"}]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["items"][0]["needs_confirmation"] is True
    assert payload["items"][0]["ai_action"] == "BLOCK_BUY"


def test_social_news_alerts_api(monkeypatch, tmp_path: Path) -> None:
    """Alerts endpoint should return alert list and safety rules."""

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())
    client.post(
        "/api/social-news/analyze",
        json={"items": [{"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"}]},
    )

    response = client.get("/api/social-news/alerts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["alerts"]
    assert payload["summary"]["block_buy"] >= 1
    assert "telegram_client" in payload
    assert "rss_reader" in payload
