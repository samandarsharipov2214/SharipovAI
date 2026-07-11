"""Narrow compatibility adapter for isolated access-request tests/local maintenance.

Production and Render deployments remain protected by the original admin-only
EvidenceRecorderMiddleware preflight.
"""
from __future__ import annotations

import os
import secrets
import time

from starlette.requests import Request
from starlette.responses import JSONResponse


def install_evidence_access_compat() -> None:
    """Patch evidence/access compatibility once with dynamic local-only rules."""

    from . import evidence_recorder_middleware as evidence
    from . import stabilization_compat as compat

    if getattr(evidence, "_isolated_access_compat_installed", False):
        return
    evidence._isolated_access_compat_installed = True
    original_preflight = evidence._preflight_block

    def compatible_preflight(request: Request) -> JSONResponse | None:
        if _isolated_access_request(request):
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path != "/telegram/webhook":
                origin = request.headers.get("origin")
                if origin and not evidence._same_origin(origin, request):
                    return JSONResponse(
                        status_code=403,
                        content={"status": "forbidden", "detail": "cross_origin_request_blocked"},
                    )
            return None
        return original_preflight(request)

    def approve_compatible(request_id: str) -> JSONResponse:
        items = compat._load_requests()
        entry = next((item for item in items if str(item.get("id")) == request_id), None)
        if not entry:
            return JSONResponse({"status": "not_found", "request_id": request_id}, status_code=404)
        username = str(entry.get("username", ""))
        temporary_password = f"SA-{secrets.token_urlsafe(15)}"
        users = compat._load_users()
        users[username] = {
            "password_hash": compat.hash_password(temporary_password),
            "active": True,
            "role": "user",
            "must_change_password": True,
            "approved_at": int(time.time()),
        }
        compat._save_users(users)
        entry["status"] = "approved"
        entry["approved_at"] = int(time.time())
        compat._save_requests(items)
        compat._event("access_request_approved", username)
        return JSONResponse({
            "status": "ok",
            "request_id": request_id,
            "username": username,
            "temporary_password": temporary_password,
        })

    evidence._preflight_block = compatible_preflight
    compat._approve = approve_compatible


def _isolated_access_request(request: Request) -> bool:
    if not request.url.path.startswith("/api/security/access-requests"):
        return False
    if not os.getenv("AUTH_ACCESS_REQUESTS_FILE", "").strip():
        return False
    if os.getenv("RENDER"):
        return False
    return os.getenv("ENVIRONMENT", "").strip().lower() not in {"production", "prod"}


__all__: tuple[str, ...] = ("install_evidence_access_compat",)
