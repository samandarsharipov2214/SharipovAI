"""Fail-closed authentication middleware for SharipovAI dashboard routes."""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse, RedirectResponse
from starlette.requests import Request

_PUBLIC_EXACT = {
    "/login",
    "/register",
    "/logout",
    "/health",
    "/api/health",
    "/startup",
    "/api/security/status",
    "/telegram/webhook",
    "/api/telegram/miniapp-auth",
    "/api/telegram/set-webhook",
    "/api/telegram/delete-webhook",
    "/api/telegram/test-message",
    "/check-ai",
    "/news-live",
    "/ai-audit",
    "/system-ai-audit",
    "/api/check-ai",
    "/api/news-live",
    "/api/ai-audit",
    "/api/system-ai-audit",
}
_PUBLIC_PREFIXES = ("/static/", "/docs", "/openapi.json", "/api/social-news/")


def auth_disabled() -> bool:
    """Auth bypass is allowed only when explicitly enabled for local tests."""
    return os.getenv("SHARIPOVAI_DISABLE_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}


def session_username(request: Request) -> str | None:
    """Resolve the existing signed dashboard session without import cycles."""
    from .app import _session_username

    return _session_username(request)


def is_public_path(path: str) -> bool:
    return path in _PUBLIC_EXACT or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


class AuthGuardMiddleware:
    """Require a signed dashboard session for every non-public HTTP route."""

    def __init__(self, app: Callable[[Any, Any, Any], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or auth_disabled():
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        if is_public_path(path) or session_username(request):
            await self.app(scope, receive, send)
            return

        if path.startswith("/api/"):
            response = JSONResponse(
                status_code=401,
                content={"status": "unauthorized", "detail": "authentication required"},
            )
        else:
            safe_path = path if path.startswith("/") and not path.startswith("//") else "/"
            response = RedirectResponse(url=f"/login?next={safe_path}", status_code=303)
        await response(scope, receive, send)
