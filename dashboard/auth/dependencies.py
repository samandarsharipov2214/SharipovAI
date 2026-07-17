"""Explicit authentication dependencies for operational routers."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

from dashboard.admin_guard import require_admin


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    username: str
    authenticated: bool = True
    admin: bool = True


def admin_principal(request: Request) -> AdminPrincipal:
    """Require an authenticated administrator and return bounded identity."""

    require_admin(request)
    try:
        from dashboard.app import _session_username

        username = _session_username(request) or "admin"
    except Exception:
        username = "admin"
    return AdminPrincipal(username=str(username)[:128])


def require_metrics_access(request: Request) -> None:
    """Permit a Prometheus token or authenticated administrator."""

    token = os.getenv("SHARIPOVAI_METRICS_TOKEN", "").strip()
    authorization = request.headers.get("authorization", "")
    if token:
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        if supplied and hmac.compare_digest(supplied, token):
            return
    try:
        require_admin(request)
        return
    except HTTPException:
        pass
    production = bool(os.getenv("RENDER")) or os.getenv(
        "ENVIRONMENT", ""
    ).strip().lower() in {"production", "prod"}
    if not production and not token:
        return
    raise HTTPException(status_code=401, detail="metrics authentication required")


__all__ = ["AdminPrincipal", "admin_principal", "require_metrics_access"]
