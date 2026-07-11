"""Narrow compatibility adapter for isolated access-request tests/local maintenance.

Production and Render deployments remain protected by the original admin-only
EvidenceRecorderMiddleware preflight.
"""
from __future__ import annotations

import os
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse


def install_evidence_access_compat() -> None:
    """Patch the evidence preflight once with a narrow dynamic local exception."""

    from . import evidence_recorder_middleware as evidence

    if getattr(evidence, "_isolated_access_compat_installed", False):
        return
    evidence._isolated_access_compat_installed = True
    original_preflight = evidence._preflight_block

    def compatible_preflight(request: Request) -> JSONResponse | None:
        if _isolated_access_request(request):
            # Preserve the original cross-origin protection while bypassing only
            # the legacy admin-only prefix for an explicitly isolated local file.
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path != "/telegram/webhook":
                origin = request.headers.get("origin")
                if origin and not evidence._same_origin(origin, request):
                    return JSONResponse(
                        status_code=403,
                        content={"status": "forbidden", "detail": "cross_origin_request_blocked"},
                    )
            return None
        return original_preflight(request)

    evidence._preflight_block = compatible_preflight


def _isolated_access_request(request: Request) -> bool:
    if not request.url.path.startswith("/api/security/access-requests"):
        return False
    if not os.getenv("AUTH_ACCESS_REQUESTS_FILE", "").strip():
        return False
    if os.getenv("RENDER"):
        return False
    return os.getenv("ENVIRONMENT", "").strip().lower() not in {"production", "prod"}


__all__: tuple[str, ...] = ("install_evidence_access_compat",)
