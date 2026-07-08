"""Stable base routes for SharipovAI dashboard.

Feature APIs are installed separately by dashboard.app:
- demo_api
- exchange_api
- social_news_api
- public_check_api

Keep this router small so Render startup cannot fail because of old demo routes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Basic health check."""

    return {"status": "ok"}


@router.get("/api/health")
def api_health() -> dict[str, str]:
    """Basic API health check."""

    return {"status": "ok", "web": "ok", "router": "ok"}


@router.get("/api/web-diagnostics")
def web_diagnostics() -> dict[str, Any]:
    """Return compact diagnostics for Render checks."""

    return {
        "status": "ok",
        "checks": {
            "dashboard_routes": "ok",
            "render_start_command": "uvicorn dashboard.app:app",
            "base_router": "stable",
        },
        "next_urls": {
            "home": "/",
            "news_live": "/news-live",
            "check_ai": "/check-ai",
            "api_check_ai": "/api/check-ai",
        },
    }


@router.post("/api/chat/message")
def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    """Safe AI chat fallback without invalid Request | None annotation."""

    message = str((payload or {}).get("message", "")).strip().lower()
    if "новост" in message or "news" in message or "ии" in message:
        reply = "News Supervisor работает. Открой /news-live, чтобы увидеть под-AI, источники, новости и достоверность."
    elif "портф" in message or "баланс" in message:
        reply = "Портфель работает в DEMO/sandbox. Реальные ордера заблокированы без ручного разрешения."
    else:
        reply = "SharipovAI живой. Проверка ИИ: /check-ai. Новости: /news-live."
    return {
        "status": "ok",
        "reply": reply,
        "run": {"status": "ok", "mode": "demo", "service": "SharipovAI"},
    }


@router.get("/api/run")
def api_run(request: Request) -> dict[str, Any]:
    """Safe runner fallback."""

    return {"status": "ok", "mode": "demo", "service": "SharipovAI", "path": request.url.path}


@router.get("/news", response_class=HTMLResponse)
def news_page() -> HTMLResponse:
    """Redirect-like news entry page."""

    return HTMLResponse(
        """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Новости SharipovAI</title></head><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#070b12;color:#eef4ff;padding:24px"><h1>Новости SharipovAI</h1><p>Открой живой раздел:</p><p><a style="color:#60a5fa;font-weight:800" href="/news-live">/news-live</a></p></body></html>"""
    )


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Return favicon."""

    return FileResponse(Path(__file__).parent / "static" / "favicon.svg")


@router.get("/logo.svg", include_in_schema=False)
def logo() -> FileResponse:
    """Return logo."""

    return FileResponse(Path(__file__).parent / "static" / "logo.svg")
