"""Shared authorization guard for sensitive SharipovAI dashboard APIs."""
from __future__ import annotations

from fastapi import HTTPException, Request


def require_admin(request: Request) -> str:
    """Require an authenticated active administrator.

    Sensitive account and execution endpoints never honor the global test-only
    auth bypass. Tests should mock the session helpers explicitly instead.
    """
    # Lazy import avoids a circular import while dashboard.app is initialized.
    from .app import _is_admin_request, _session_username

    username = _session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})
    if not _is_admin_request(request):
        raise HTTPException(status_code=403, detail={"status": "forbidden"})
    return username
