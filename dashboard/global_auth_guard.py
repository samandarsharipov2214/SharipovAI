"""Fail-closed global authentication middleware for the SharipovAI dashboard."""
from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

_PUBLIC_EXACT = {
    "/",
    "/login",
    "/register",
    "/logout",
    "/health",
    "/api/health",
    "/startup",
    "/api/security/status",
}
_PUBLIC_PREFIXES = ("/static/", "/docs", "/openapi.json")
_TRUE_VALUES = {"1", "true", "yes", "on"}


def auth_disabled() -> bool:
    """Return True only after an explicit test/development bypass."""
    return os.getenv("SHARIPOVAI_DISABLE_AUTH", "0").strip().lower() in _TRUE_VALUES


def install_global_auth_guard(app: FastAPI) -> None:
    """Require a valid session for every non-public route.

    The bypass defaults to disabled. Sensitive Bybit routes retain their own
    administrator guard and therefore remain protected even when this global
    middleware is explicitly bypassed for tests.
    """
    if getattr(app.state, "global_auth_guard_installed", False):
        return
    app.state.global_auth_guard_installed = True

    @app.middleware("http")
    async def global_auth_guard(request: Request, call_next):
        if auth_disabled():
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_EXACT or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)

        from .app import _session_username

        if _session_username(request):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse(
                {"status": "unauthorized", "detail": "authentication required"},
                status_code=401,
            )

        safe_next = path if path.startswith("/") and not path.startswith("//") else "/"
        return RedirectResponse(url=f"/login?next={quote(safe_next, safe='/')}", status_code=303)
