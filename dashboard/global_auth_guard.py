"""Fail-closed global authentication middleware for the SharipovAI dashboard."""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .auth_saas import resolve_authenticated_principal
from .internal_service_auth import require_internal_service

_PUBLIC_EXACT = {
    "/",
    "/app",
    "/login",
    "/register",
    "/logout",
    "/health",
    "/api/health",
    "/startup",
    "/api/security/status",
    "/api/release/status",
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
_LOCAL_READONLY_EXACT = {"/api/market/bybit-websocket/status"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _is_private_ip(host: str) -> bool:
    """Проверяет, принадлежит ли IP частной сети (RFC 1918)."""
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) == 4:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
    return False


def _client_host(request: Request) -> str:
    """Return the direct ASGI peer host without trusting proxy headers."""
    if not request.client or not request.client.host:
        return ""
    return request.client.host.strip().split("%", 1)[0]


def _is_loopback_request(request: Request) -> bool:
    value = _client_host(request)
    if not value:
        return False
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def auth_disabled() -> bool:
    """Return True only after an explicit test/development bypass."""
    if bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}:
        return False
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
    """Require service auth for internal routes and user auth elsewhere."""

    if getattr(app.state, "global_auth_guard_installed", False):
        return
    app.state.global_auth_guard_installed = True
    _session_resolver(app)

    @app.middleware("http")
    async def global_auth_guard(request: Request, call_next: Callable[[Request], Any]):
        path = request.url.path
        if path.startswith("/internal/"):
            try:
                require_internal_service(request)
            except HTTPException as exc:
                return JSONResponse(
                    {"detail": exc.detail},
                    status_code=exc.status_code,
                    headers={"Cache-Control": "no-store"},
                )
            return await call_next(request)

        client_host = _client_host(request)
        if path in _LOCAL_READONLY_EXACT and (
            _is_loopback_request(request) or _is_private_ip(client_host)
        ):
            return await call_next(request)

        if auth_disabled():
            return await call_next(request)

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


__all__ = [
    "_client_host",
    "_is_loopback_request",
    "_is_private_ip",
    "auth_disabled",
    "install_global_auth_guard",
]
