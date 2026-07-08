"""Dashboard API endpoints for Social News Monitor."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from news_monitor.analyzer import analyzed_news_payload
from news_monitor.sources import sources_payload
from news_monitor.storage import load_news_state, save_news_state
from news_monitor.telegram_client import read_latest_messages, telegram_client_status


def install_social_news_api(app: FastAPI) -> None:
    """Install Social News Monitor API endpoints."""

    if getattr(app.state, "social_news_api_installed", False):
        return
    app.state.social_news_api_installed = True

    @app.get("/api/social-news")
    def social_news() -> dict[str, object]:
        """Return latest analyzed social/news state."""

        state = load_news_state()
        state["telegram_client"] = telegram_client_status()
        return {"status": "ok", **state}

    @app.get("/api/social-news/sources")
    def social_news_sources() -> dict[str, object]:
        """Return monitored source definitions."""

        return {"status": "ok", **sources_payload(), "telegram_client": telegram_client_status()}

    @app.get("/api/social-news/telegram/status")
    def social_news_telegram_status() -> dict[str, object]:
        """Return Telegram client setup status without exposing secrets."""

        return {"status": "ok", "telegram_client": telegram_client_status()}

    @app.post("/api/social-news/telegram/refresh")
    def social_news_telegram_refresh(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Read allowlisted Telegram sources and analyze messages.

        This reads only if TELEGRAM_CLIENT_ENABLED=1 and all credentials are set.
        Otherwise it returns a safe disabled status.
        """

        limit = _safe_int((payload or {}).get("limit_per_source"), 5)
        result = read_latest_messages(limit_per_source=limit)
        if result.get("status") != "ok":
            return {"status": "disabled", "telegram": result.get("telegram", telegram_client_status()), "items": [], "news": load_news_state().get("news", {})}
        analyzed = analyzed_news_payload(result.get("items", []))
        state = load_news_state()
        state["news"] = analyzed
        state["telegram_client"] = result.get("telegram", telegram_client_status())
        save_news_state(state)
        return {"status": "ok", "telegram": result.get("telegram", {}), "items": result.get("items", []), "news": analyzed}

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
            "telegram_client": telegram_client_status(),
        }


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)
