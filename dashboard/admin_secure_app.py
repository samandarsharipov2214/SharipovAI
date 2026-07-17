"""Admin-protected SharipovAI entrypoint.

Run with:
    python -m uvicorn dashboard.admin_secure_app:app --reload
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .app import _load_access_requests, _load_users, _record_security_event, _session_username
from .final_ci_contracts import install_final_ci_contracts
from .menu_visibility import hide_security_link_for_non_admin
from .roles import is_admin, resolve_role
from .secure_app import create_secure_app

SECURITY_PATHS = ("/security", "/api/security")


def create_admin_secure_app(runner_factory: Any | None = None):
    """Create app with login lockout, role menu and admin-only security center."""
    dashboard = create_secure_app(runner_factory=runner_factory)
    dashboard.add_middleware(RoleAwareMenuMiddleware)
    dashboard.add_middleware(AdminOnlySecurityMiddleware)
    dashboard.add_middleware(AdminAccessContractMiddleware)

    @dashboard.get("/security", response_class=HTMLResponse)
    def security_center(request: Request) -> HTMLResponse:
        username = _session_username(request) or "admin"
        requests = _load_access_requests()
        pending = [entry for entry in requests.values() if isinstance(entry, dict) and entry.get("status") == "pending"]
        return HTMLResponse(_security_center_html(username=username, pending_count=len(pending)))

    @dashboard.get("/api/auth/role")
    def auth_role(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        role = resolve_role(username, _load_users()) if username else None
        if username and role is None:
            try:
                from . import stabilization_compat as compat

                role = resolve_role(username, compat._load_users())
            except Exception:
                role = None
        return {"authenticated": bool(username), "user": username, "role": role, "admin": role == "admin"}

    # Security middleware is added after the canonical dashboard factory. Promote
    # the authoritative configured-admin/session contract once more so it becomes
    # the outermost layer and every security middleware sees the same identity.
    install_final_ci_contracts(dashboard, force_outer=True)
    return dashboard


class AdminAccessContractMiddleware:
    """Serve the stable request list/approval format to authenticated admins."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        prefix = "/api/security/access-requests"
        if not path.startswith(prefix):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        username = _session_username(request)
        users = _load_users()
        if not is_admin(username, users):
            await self.app(scope, receive, send)
            return

        from . import stabilization_compat as compat

        if method == "GET" and path == prefix:
            response = JSONResponse({"status": "ok", "requests": compat._load_requests()})
            await response(scope, receive, send)
            return
        suffix = "/approve"
        if method == "POST" and path.startswith(prefix + "/") and path.endswith(suffix):
            request_id = path[len(prefix) + 1:-len(suffix)]
            response = compat._approve(request_id)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RoleAwareMenuMiddleware:
    """Hide admin-only menu items from non-admin users."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        username = _session_username(request)
        admin = is_admin(username, _load_users())
        captured: list[Message] = []

        async def capture_send(message: Message) -> None:
            captured.append(message)

        await self.app(scope, receive, capture_send)

        content_type = ""
        for message in captured:
            if message.get("type") == "http.response.start":
                content_type = _header_value(message.get("headers", []), b"content-type")
                break

        if "text/html" not in content_type:
            for message in captured:
                await send(message)
            return

        body = b"".join(message.get("body", b"") for message in captured if message.get("type") == "http.response.body")
        text = hide_security_link_for_non_admin(body.decode("utf-8"), admin=admin)
        body_bytes = text.encode("utf-8")

        for message in captured:
            if message.get("type") == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"content-length"]
                await send({**message, "headers": headers})
            elif message.get("type") == "http.response.body":
                await send({"type": "http.response.body", "body": body_bytes, "more_body": False})
                break
            else:
                await send(message)


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
        users = _load_users()
        try:
            from . import stabilization_compat as compat

            users = {**users, **compat._load_users()}
        except Exception:
            pass
        if is_admin(username, users):
            await self.app(scope, receive, send)
            return

        role = resolve_role(username, users) or "none"
        _record_security_event("security_access_denied", username or "anonymous", request, {"path": path, "role": role})
        if path.startswith("/api/"):
            response = Response('{"error":"admin_required"}', status_code=403, media_type="application/json")
        else:
            response = HTMLResponse(_forbidden_page_html(), status_code=403)
        await response(scope, receive, send)


def _is_security_path(path: str) -> bool:
    return any(path == item or path.startswith(f"{item}/") for item in SECURITY_PATHS)


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for key, value in headers:
        if key.lower() == name.lower():
            return value.decode("latin1")
    return ""


def _security_center_html(*, username: str, pending_count: int) -> str:
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SharipovAI · Кибер-безопасность</title><style>body{{min-height:100vh;margin:0;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}}main{{width:min(920px,92vw);margin:40px auto}}.card{{border:1px solid #38bdf844;background:#071426;border-radius:28px;padding:24px;box-shadow:0 30px 80px #0008}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}.stat{{border:1px solid #ffffff18;border-radius:18px;padding:16px;background:#0b1b2c}}small{{color:#94a3b8}}a{{color:#7dd3fc}}</style></head><body><main><h1>Кибер-безопасность</h1><p>Администратор: {escape(username)}</p><section class='card'><div class='grid'><div class='stat'><small>Статус</small><h2>Защищено</h2></div><div class='stat'><small>Заявки</small><h2>{pending_count}</h2></div><div class='stat'><small>Роль</small><h2>admin</h2></div></div><p><a href='/api/security/access-requests'>Открыть заявки доступа</a></p></section></main></body></html>"""


def _forbidden_page_html() -> str:
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Доступ запрещён</title><style>body{min-height:100vh;display:grid;place-items:center;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}.card{width:min(520px,92vw;border:1px solid #ff6b7555;background:#071426;border-radius:28px;padding:28px;box-shadow:0 30px 80px #0008}h1{margin:0 0 10px}.error{color:#ffadb5}a{color:#7dd3fc;font-weight:800}</style></head><body><main class="card"><h1>Доступ запрещён</h1><p class="error">Раздел кибер-безопасности доступен только админу.</p><p><a href="/">Вернуться в SharipovAI</a></p></main></body></html>"""


app = create_admin_secure_app()
