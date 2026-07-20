"""Fail-closed global authentication middleware for the SharipovAI dashboard."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .auth_saas import resolve_authenticated_principal

_PUBLIC_EXACT = {
    "/login",
    "/register",
    "/logout",
    "/health",
    "/api/health",
    "/startup",
    "/api/security/status",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/billing/webhook",
    "/api/markets/overview",
    "/metrics",
    "/telegram/webhook",
}
_PUBLIC_PREFIXES = ("/static/", "/docs", "/openapi.json")
_TRUE_VALUES = {"1", "true", "yes", "on"}


def auth_disabled() -> bool:
    """Return True only after an explicit test/development bypass."""

    return os.getenv("SHARIPOVAI_DISABLE_AUTH", "0").strip().lower() in _TRUE_VALUES


def _session_resolver(app: FastAPI) -> Callable[[Request], str | None]:
    """Resolve the canonical session function while preserving legacy test hooks."""

    override = getattr(app, "_session_username", None)
    if callable(override):
        return override
    from .app import _session_username

    app._session_username = _session_username
    return _session_username


def _principal(request: Request, app: FastAPI) -> str | None:
    jwt_principal = resolve_authenticated_principal(request)
    if jwt_principal:
        return jwt_principal
    resolver = _session_resolver(app)
    try:
        return resolver(request)
    except Exception:
        return None


def install_global_auth_guard(app: FastAPI) -> None:
    """Require a valid session or JWT cookie for every non-public route."""

    if getattr(app.state, "global_auth_guard_installed", False):
        return
    app.state.global_auth_guard_installed = True
    _session_resolver(app)

    @app.middleware("http")
    async def global_auth_guard(request: Request, call_next: Callable[[Request], Any]):
        if auth_disabled():
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_EXACT or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)

        username = _principal(request, app)
        if username:
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse(
                {"status": "unauthorized", "detail": "authentication required"},
                status_code=401,
            )

        safe_next = path if path.startswith("/") and not path.startswith("//") else "/"
        return RedirectResponse(
            url=f"/login?next={quote(safe_next, safe='/')}",
            status_code=303,
        )


__all__ = ["auth_disabled", "install_global_auth_guard"]
