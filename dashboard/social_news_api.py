"""Dashboard API endpoints for Social News Monitor."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from news_monitor.analyzer import analyzed_news_payload
from news_monitor.sources import sources_payload
from news_monitor.storage import load_news_state, save_news_state


def install_social_news_api(app: FastAPI) -> None:
    """Install Social News Monitor API endpoints."""

    if getattr(app.state, "social_news_api_installed", False):
        return
    app.state.social_news_api_installed = True

    @app.get("/api/social-news")
    def social_news() -> dict[str, object]:
        """Return latest analyzed social/news state."""

        state = load_news_state()
        return {"status": "ok", **state}

    @app.get("/api/social-news/sources")
    def social_news_sources() -> dict[str, object]:
        """Return monitored source definitions."""

        return {"status": "ok", **sources_payload()}

    @app.post("/api/social-news/analyze")
    def social_news_analyze(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Analyze submitted raw social/news items."""

        data = payload or {}
        raw_items = data.get("items") if isinstance(data.get("items"), list) else None
        analyzed = analyzed_news_payload(raw_items)
        state = load_news_state()
        state["news"] = analyzed
        save_news_state(state)
        return analyzed

    @app.get("/api/social-news/alerts")
    def social_news_alerts() -> dict[str, object]:
        """Return high-urgency alerts."""

        state = load_news_state()
        news = state.get("news", {}) if isinstance(state.get("news"), dict) else {}
        return {
            "status": "ok",
            "summary": news.get("summary", {}),
            "alerts": news.get("alerts", []),
            "rules": news.get("rules", []),
        }
