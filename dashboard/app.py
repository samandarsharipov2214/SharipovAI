"""FastAPI application factory for the SharipovAI dashboard.

Render currently starts the service with:

    uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT

So this module must expose a module-level `app` object. Keep this file small and
stable; feature APIs are installed by their own modules.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from runner import SharipovAIRunner

from .policy_guard_middleware import install_policy_guard_middleware
from .routes import router


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app_instance = FastAPI(title="SharipovAI OS")
    app_instance.state.runner_factory = runner_factory or SharipovAIRunner
    app_instance.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app_instance.include_router(router)
    _install_feature_apis(app_instance)
    install_policy_guard_middleware(app_instance)
    _install_public_entrypoints(app_instance)
    return app_instance


def _install_feature_apis(app_instance: FastAPI) -> None:
    """Install optional feature APIs without breaking startup if one module fails."""

    installers: list[tuple[str, str]] = [
        ("dashboard.exchange_api", "install_exchange_api"),
        ("dashboard.demo_api", "install_demo_api"),
        ("dashboard.social_news_api", "install_social_news_api"),
        ("dashboard.public_check_api", "install_public_check_api"),
        ("dashboard.trading_intelligence_api", "install_trading_intelligence_api"),
        ("dashboard.telegram_webhook_api", "install_telegram_webhook_api"),
        ("dashboard.learning_os_api", "install_learning_os_api"),
    ]
    for module_name, function_name in installers:
        try:
            module = __import__(module_name, fromlist=[function_name])
            installer = getattr(module, function_name)
            installer(app_instance)
        except Exception as exc:  # pragma: no cover - startup safety fallback
            _install_feature_error_endpoint(app_instance, module_name, exc)


def _install_feature_error_endpoint(app_instance: FastAPI, module_name: str, exc: Exception) -> None:
    """Expose a compact startup warning without failing the whole backend."""

    error_key = module_name.replace(".", "_").replace("-", "_")

    @app_instance.get(f"/api/startup-warning/{error_key}")
    def startup_warning() -> dict[str, Any]:
        return {"status": "warning", "module": module_name, "error": f"{type(exc).__name__}: {exc}"}


def _install_public_entrypoints(app_instance: FastAPI) -> None:
    """Install simple public pages for mobile checks."""

    @app_instance.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app_instance.get("/api/health")
    def api_health() -> dict[str, str]:
        return {"status": "ok"}

    @app_instance.get("/", response_class=HTMLResponse)
    def root_page() -> HTMLResponse:
        headlines = _home_headlines()
        return HTMLResponse(
            f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI</title><style>body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{padding:18px;max-width:980px;margin:auto}}.card{{background:#111827;border:1px solid #253047;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}}.news{{background:#0b1220;border:1px solid #1f2a3d;border-radius:16px;padding:13px}}.news b{{display:block;margin-bottom:7px}}small{{color:#8ea2c4;display:block;line-height:1.4}}a{{color:#60a5fa;font-weight:800}}.ok{{display:inline-block;background:#10b981;color:#04140d;border-radius:999px;padding:7px 12px;font-weight:900}}.nav{{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}}</style></head><body><main><section class="card"><span class="ok">LIVE</span><h1>SharipovAI живой</h1><p>Система показывает новости, AI Scoreboard, Trade Gate, Learning OS и Telegram webhook.</p><div class="nav"><a href="/news-live">Новости</a><a href="/ai-scoreboard">AI Scoreboard</a><a href="/trade-gate">Можно ли торговать?</a><a href="/learning-os">Learning OS</a><a href="/learning-v2">Learning V2</a><a href="/system-ai-audit">Все ИИ</a><a href="/api/telegram/status">Telegram Status</a></div></section><section class="card"><h2>Самые обсуждаемые новости</h2><div class="grid">{headlines}</div></section><section class="card"><h2>Быстрая проверка</h2><p><a href="/api/ai-scoreboard">JSON AI Scoreboard</a></p><p><a href="/api/trade-gate">JSON Trade Gate</a></p><p><a href="/api/learning-os/snapshot">JSON Learning OS</a></p><p><a href="/api/telegram/status">JSON Telegram Bot</a></p></section></main></body></html>"""
        )


def _home_headlines() -> str:
    """Return compact news cards for the home page."""

    try:
        from news_monitor.analyzer import analyzed_news_payload

        news = analyzed_news_payload()
        items = list(news.get("items", []))[:6]
    except Exception as exc:  # pragma: no cover - safe public fallback
        return f"<article class='news'><b>Новости временно недоступны</b><small>{escape(type(exc).__name__)}</small></article>"
    if not items:
        return "<article class='news'><b>Новостей пока нет</b><small>Жду обновления источников</small></article>"
    cards = []
    for item in items:
        title = escape(str(item.get("title", "Новость")))
        source = escape(str(item.get("source_name", "Источник")))
        credibility = escape(str(item.get("credibility_percent", item.get("trust_score", 0))))
        action = escape(str(item.get("ai_action", "WATCH")))
        cards.append(f"<article class='news'><b>{title}</b><small>{source}</small><small>Достоверность: {credibility}% · AI: {action}</small></article>")
    return "".join(cards)


# Required for Render start command: uvicorn dashboard.app:app
app = create_app()


__all__ = ("app", "create_app")