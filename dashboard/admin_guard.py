"""Shared authorization guard for sensitive SharipovAI dashboard APIs."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

_SENSITIVE_PATHS = {
    "/api/exchange/account/status",
    "/api/exchange/account/snapshot",
    "/api/exchange/account/sync",
    "/api/exchange/private-order-ws/status",
    "/api/exchange/private-order-ws/snapshot",
    "/api/exchange/private-order-ws/reconcile",
    "/api/execution/stage-status",
    "/api/execution/testnet-order",
}
_SENSITIVE_PREFIXES = (
    "/api/campaigns/phase10/",
    "/api/performance/phase10/",
    "/api/risk/phase10/",
    "/api/production/phase11/",
)


def require_admin(request: Request) -> str:
    """Require explicit auth configuration and an active administrator."""
    if not all(os.getenv(name, "").strip() for name in ("AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD")):
        raise HTTPException(status_code=503, detail={"status": "auth_not_configured"})
    from .app import _is_admin_request, _session_username

    username = _session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})
    if not _is_admin_request(request):
        raise HTTPException(status_code=403, detail={"status": "forbidden"})
    return username


def _is_sensitive_path(path: str) -> bool:
    return path in _SENSITIVE_PATHS or any(path.startswith(prefix) for prefix in _SENSITIVE_PREFIXES)


def install_sensitive_api_guard(app: FastAPI) -> None:
    """Authorize sensitive paths before FastAPI parses request bodies."""
    if getattr(app.state, "sensitive_api_guard_installed", False):
        return
    app.state.sensitive_api_guard_installed = True

    @app.middleware("http")
    async def sensitive_api_guard(request: Request, call_next):
        if _is_sensitive_path(request.url.path):
            try:
                require_admin(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)


__all__ = ["install_sensitive_api_guard", "require_admin"]
