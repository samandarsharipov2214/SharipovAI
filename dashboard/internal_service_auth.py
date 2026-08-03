"""Authentication for localhost-only SharipovAI service endpoints."""
from __future__ import annotations

import ipaddress
import os
import secrets

from fastapi import HTTPException, Request

_HEADER = "X-SharipovAI-Service-Token"
_ENV = "SHARIPOVAI_SERVICE_TOKEN"


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    value = host.strip().split("%", 1)[0]
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def require_internal_service(request: Request) -> None:
    """Require a direct loopback caller and a constant-time service token match."""

    client_host = request.client.host if request.client else None
    if not _is_loopback(client_host):
        raise HTTPException(status_code=403, detail={"status": "internal_only"})

    expected = os.getenv(_ENV, "").strip()
    supplied = request.headers.get(_HEADER, "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail={"status": "service_token_not_configured"})
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail={"status": "invalid_service_token"})


__all__ = ["require_internal_service"]
