"""Shared authorization guard for sensitive SharipovAI dashboard APIs."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

_SENSITIVE_PATHS = {
    "/api/exchange/account/status",
    "/api/exchange/account/snapshot",
    "/api/exchange/account/sync",
    "/api/execution/stage-status",
    "/api/execution/testnet-order",
}


def require_admin(request: Request) -> str:
    """Require configured authentication and an active administrator."""
    auth_secret = os.getenv("AUTH_SECRET", "").strip()
    admin_username = os.getenv("ADMIN_USERNAME", "").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not auth_secret or not admin_username or not admin_password:
        raise HTTPException(status_code=503, detail={"status": "auth_not_configured"})

    # Lazy import avoids a circular import while dashboard.app is initialized.
    from .app import _is_admin_request, _session_username

    username = _session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})
    if not _is_admin_request(request):
        raise HTTPException(status_code=403, detail={"status": "forbidden"})
    return username


def install_sensitive_api_guard(app: FastAPI) -> None:
    """Authorize sensitive paths before FastAPI parses or validates request bodies."""
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
