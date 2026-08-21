"""Shared authorization guard for sensitive SharipovAI dashboard APIs."""
from __future__ import annotations

import os
from typing import Any

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
    "/api/campaigns/phase9/",
    "/api/campaigns/phase10/",
    "/api/performance/phase10/",
    "/api/risk/phase10/",
    "/api/production/phase11/",
    "/api/learning/phase12/",
)
_DEFAULT_LOCAL_JWT_SECRET = "local-dev-jwt-secret-change-me"


def _explicit_canonical_jwt_secret() -> str | None:
    """Return only an explicitly configured non-default JWT signing secret."""

    configured = os.getenv("JWT_SECRET", "").strip() or os.getenv("AUTH_SECRET", "").strip()
    if not configured or configured == _DEFAULT_LOCAL_JWT_SECRET:
        return None
    return configured


def _canonical_saas_user(request: Request) -> Any | None:
    """Return an active canonical SaaS user only when JWT auth is explicitly configured."""

    if _explicit_canonical_jwt_secret() is None:
        return None
    try:
        from .auth_saas import get_current_user
        from .db_saas import SessionLocal

        db = SessionLocal()
        try:
            user = get_current_user(request, db)
            if user and user.is_active:
                return user
        finally:
            db.close()
    except Exception:
        return None
    return None


def require_admin(request: Request) -> str:
    """Require an active administrator from canonical SaaS or legacy auth."""

    canonical_user = _canonical_saas_user(request)
    if canonical_user is not None:
        if str(canonical_user.role or "").lower() != "admin":
            raise HTTPException(status_code=403, detail={"status": "forbidden"})
        return str(canonical_user.email)

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
