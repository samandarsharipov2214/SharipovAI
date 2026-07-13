"""Tests for the canonical Social News Monitor dashboard API."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dashboard import create_app


def test_social_news_api_returns_truthful_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    payload = TestClient(create_app()).get("/api/social-news").json()
    assert payload["status"] == "ok"
    assert payload["sources"]["total"] >= 50
    assert payload["news"]["summary"]["total"] >= 0
    assert payload["rss_enabled"] is True
    assert payload.get("synthetic_fallback_used") is False
    assert "telegram_client" in payload
    assert "rss_reader" in payload
    assert "agents" in payload
    assert payload["agents"]["supervisor"]["name"] == "Main News Supervisor AI"


def test_social_news_sources_api(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    payload = TestClient(create_app()).get("/api/social-news/agents").json()
    assert payload["status"] == "ok"
    assert payload["supervisor"]["agent_count"] >= 8
    assert any(agent["id"] == "sports_news_ai" for agent in payload["agents"])
    assert any(agent["id"] == "weather_news_ai" for agent in payload["agents"])
    assert any(agent["id"] == "telegram_news_ai" for agent in payload["agents"])
    assert any(agent["id"] == "x_news_ai" for agent in payload["agents"])


def test_social_news_supervisor_api(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())
    client.post(
        "/api/social-news/analyze",
        json={"items": [{"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"}]},
    )
    payload = client.get("/api/social-news/supervisor").json()
    assert payload["status"] == "ok"
    assert payload["supervisor"]["name"] == "Main News Supervisor AI"
    assert payload["supervisor"]["decision"] == "BLOCK_BUY_AND_VERIFY"
    assert payload["agents"]


def test_social_news_rss_status_api(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    payload = TestClient(create_app()).get("/api/social-news/rss/status").json()
    assert payload["status"] == "ok"
    assert payload["rss_reader"]["enabled"] is True
    assert payload["rss_reader"]["source_count"] >= 1


def test_social_news_rss_refresh_api(monkeypatch, tmp_path: Path) -> None:
    import news_monitor.rss_reader as rss_reader

    class Response:
        status_code = 200
        content = b"<rss><channel><item/></channel></rss>"
        headers = {"content-type": "application/rss+xml"}

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, _url: str) -> Response:
            return Response()

    def fake_parse(_payload: bytes) -> SimpleNamespace:
        return SimpleNamespace(
            bozo=False,
            entries=[
                {
                    "title": "BTC ETF inflow update",
                    "summary": "Bitcoin market inflow summary",
                    "link": "https://example.com/btc",
                    "published_parsed": (2026, 1, 2, 3, 4, 5, 0, 0, 0),
                }
            ],
        )

    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    monkeypatch.setattr(rss_reader.httpx, "Client", Client)
    monkeypatch.setattr(rss_reader.feedparser, "parse", fake_parse)
    payload = TestClient(create_app()).post(
        "/api/social-news/rss/refresh", json={"limit_per_source": 1}
    ).json()
    assert payload["status"] == "ok"
    assert payload["items"]
    assert payload["news"]["summary"]["total"] >= 1
    assert payload["agents"]["supervisor"]["agent_count"] >= 8


def test_social_news_telegram_status_when_not_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING", "TELEGRAM_NEWS_SOURCES"):
        monkeypatch.delenv(name, raising=False)
    payload = TestClient(create_app()).get("/api/social-news/telegram/status").json()
    assert payload["status"] == "ok"
    telegram = payload["telegram_client"]
    assert telegram["configured"] is False
    missing = set(telegram["missing"])
    assert {"TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING"} <= missing
    assert "api_hash" not in telegram
    assert "session_string" not in telegram


def test_social_news_telegram_refresh_disabled_when_not_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    monkeypatch.delenv("TELEGRAM_CLIENT_ENABLED", raising=False)
    payload = TestClient(create_app()).post(
        "/api/social-news/telegram/refresh", json={"limit_per_source": 2}
    ).json()
    assert payload["status"] == "disabled"
    assert payload["items"] == []
    assert "news" in payload


def test_social_news_analyze_api_blocks_unconfirmed_social_claim(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    payload = TestClient(create_app()).post(
        "/api/social-news/analyze",
        json={"items": [{"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"}]},
    ).json()
    assert payload["status"] == "ok"
    assert payload["items"][0]["needs_confirmation"] is True
    assert payload["items"][0]["ai_action"] == "BLOCK_BUY"
    assert payload["agents"]["supervisor"]["decision"] == "BLOCK_BUY_AND_VERIFY"


def test_social_news_alerts_api(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_MONITOR_STATE_FILE", str(tmp_path / "news_state.json"))
    client = TestClient(create_app())
    client.post(
        "/api/social-news/analyze",
        json={"items": [{"source_id": "watcher_guru_x", "title": "Breaking: BTC hack liquidation alert"}]},
    )
    payload = client.get("/api/social-news/alerts").json()
    assert payload["status"] == "ok"
    assert payload["alerts"]
    assert payload["summary"]["block_buy"] >= 1
    assert "telegram_client" in payload
    assert "rss_reader" in payload
    assert payload["supervisor"]["decision"] == "BLOCK_BUY_AND_VERIFY"
