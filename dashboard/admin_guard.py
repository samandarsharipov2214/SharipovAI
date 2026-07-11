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


def install_sensitive_api_guard(app: FastAPI) -> None:
    """Authorize sensitive paths before FastAPI parses request bodies."""
    if getattr(app.state, "sensitive_api_guard_installed", False):
        return
    app.state.sensitive_api_guard_installed = True

    @app.middleware("http")
    async def sensitive_api_guard(request: Request, call_next):
        if request.url.path in _SENSITIVE_PATHS:
            try:
                require_admin(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)
