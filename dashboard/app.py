"""FastAPI application factory for the SharipovAI dashboard.

Render currently starts the service with:

    uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT

So this module must expose a module-level `app` object. Keep this file small and
stable; feature APIs are installed by their own modules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from runner import SharipovAIRunner

from .routes import router


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app_instance = FastAPI(title="SharipovAI OS")
    app_instance.state.runner_factory = runner_factory or SharipovAIRunner
    app_instance.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app_instance.include_router(router)
    _install_feature_apis(app_instance)
    _install_public_entrypoints(app_instance)
    return app_instance


def _install_feature_apis(app_instance: FastAPI) -> None:
    """Install optional feature APIs without breaking startup if one module fails."""

    installers: list[tuple[str, str]] = [
        ("dashboard.exchange_api", "install_exchange_api"),
        ("dashboard.demo_api", "install_demo_api"),
        ("dashboard.social_news_api", "install_social_news_api"),
        ("dashboard.public_check_api", "install_public_check_api"),
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
        return HTMLResponse(
            """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI</title><style>body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:22px;max-width:760px;margin:auto}.card{background:#111827;border:1px solid #253047;border-radius:18px;padding:18px;margin:14px 0}a{color:#60a5fa;font-weight:700}.ok{display:inline-block;background:#10b981;color:#04140d;border-radius:999px;padding:7px 12px;font-weight:900}</style></head><body><main><section class="card"><span class="ok">LIVE</span><h1>SharipovAI backend работает</h1><p>Открой проверку ИИ:</p><p><a href="/check-ai">Проверить ИИ</a></p><p><a href="/api/check-ai">JSON проверка</a></p></section></main></body></html>"""
        )


# Required for Render start command: uvicorn dashboard.app:app
app = create_app()


__all__ = ("app", "create_app")
