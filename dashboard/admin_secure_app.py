"""Admin-protected SharipovAI entrypoint.

Run with:
    python -m uvicorn dashboard.admin_secure_app:app --reload
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .app import _load_users, _record_security_event, _session_username
from .roles import is_admin, resolve_role
from .secure_app import create_secure_app


SECURITY_PATHS = ("/security", "/api/security")


def create_admin_secure_app(runner_factory: Any | None = None):
    """Create app with login lockout and admin-only security center."""

    dashboard = create_secure_app(runner_factory=runner_factory)
    dashboard.add_middleware(AdminOnlySecurityMiddleware)

    @dashboard.get("/api/auth/role")
    def auth_role(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        role = resolve_role(username, _load_users()) if username else None
        return {"authenticated": bool(username), "user": username, "role": role, "admin": role == "admin"}

    return dashboard


class AdminOnlySecurityMiddleware:
    """Protect security center from non-admin users."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if not _is_security_path(path):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        username = _session_username(request)
        if is_admin(username, _load_users()):
            await self.app(scope, receive, send)
            return

        role = resolve_role(username, _load_users()) or "none"
        _record_security_event("security_access_denied", username or "anonymous", request, {"path": path, "role": role})
        if path.startswith("/api/"):
            response = Response('{"error":"admin_required"}', status_code=403, media_type="application/json")
        else:
            response = HTMLResponse(_forbidden_page_html(), status_code=403)
        await response(scope, receive, send)


def _is_security_path(path: str) -> bool:
    return any(path == item or path.startswith(f"{item}/") for item in SECURITY_PATHS)


def _forbidden_page_html() -> str:
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Доступ запрещён</title><style>body{min-height:100vh;display:grid;place-items:center;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}.card{width:min(520px,92vw);border:1px solid #ff6b7555;background:#071426;border-radius:28px;padding:28px;box-shadow:0 30px 80px #0008}h1{margin:0 0 10px}.error{color:#ffadb5}a{color:#7dd3fc;font-weight:800}</style></head><body><main class="card"><h1>Доступ запрещён</h1><p class="error">Раздел кибер-безопасности доступен только админу.</p><p><a href="/">Вернуться в SharipovAI</a></p></main></body></html>"""


app = create_admin_secure_app()
