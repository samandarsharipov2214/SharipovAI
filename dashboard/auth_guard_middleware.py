"""Compatibility authentication middleware used by ``create_app`` instances.

The production entrypoint installs ``global_auth_guard`` separately and remains
fail-closed. This middleware preserves the historical app-factory contract:
authentication is enforced when ``SHARIPOVAI_DISABLE_AUTH`` is explicitly false,
while isolated local/test app instances remain usable when the variable is absent.
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from fastapi.responses import JSONResponse, RedirectResponse
from starlette.requests import Request

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_PUBLIC_EXACT = {
    "/",
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
_PUBLIC_PREFIXES = (
    "/static/",
    "/docs",
    "/openapi.json",
    "/api/social-news/",
    "/favicon.ico",
    "/logo.svg",
)


def factory_auth_enabled() -> bool:
    """Return True only when factory-level auth is explicitly requested."""

    raw = os.getenv("SHARIPOVAI_DISABLE_AUTH")
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return False
    return normalized in _FALSE_VALUES


def session_username(request: Request) -> str | None:
    """Resolve the existing signed dashboard session without import cycles."""

    from .app import _session_username

    return _session_username(request)


def is_public_path(path: str) -> bool:
    return path in _PUBLIC_EXACT or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


class AuthGuardMiddleware:
    """Protect private app-factory routes when auth is explicitly enabled."""

    def __init__(self, app: Callable[[Any, Any, Any], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not factory_auth_enabled():
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        if is_public_path(path) or session_username(request):
            await self.app(scope, receive, send)
            return

        if path.startswith("/api/"):
            response = JSONResponse({"error": "authentication_required"}, status_code=401)
        else:
            safe_path = path if path.startswith("/") and not path.startswith("//") else "/"
            response = RedirectResponse(
                url=f"/login?next={quote(safe_path, safe='/')}",
                status_code=303,
            )
        await response(scope, receive, send)


# Backward-compatible name used by older imports/tests.
def auth_disabled() -> bool:
    return not factory_auth_enabled()


__all__ = [
    "AuthGuardMiddleware",
    "auth_disabled",
    "factory_auth_enabled",
    "is_public_path",
    "session_username",
]
