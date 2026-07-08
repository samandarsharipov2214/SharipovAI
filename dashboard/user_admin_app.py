"""SharipovAI user-management entrypoint.

Run with:
    python -m uvicorn dashboard.user_admin_app:app --reload
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from .admin_secure_app import create_admin_secure_app
from .app import _load_users, _record_security_event, _save_users, _session_username
from .user_admin import list_users, reset_user_password, set_user_active, set_user_role


def create_user_admin_app(runner_factory: Any | None = None):
    """Create app with admin-only user management APIs."""

    dashboard = create_admin_secure_app(runner_factory=runner_factory)

    @dashboard.get("/security/users", response_class=HTMLResponse)
    def users_page() -> HTMLResponse:
        rows = "".join(_user_row(user) for user in list_users(_load_users())) or "<tr><td colspan='5'>Пользователей пока нет</td></tr>"
        return HTMLResponse(
            f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Пользователи</title><link rel="stylesheet" href="/static/style.css?v=20260709-01"></head><body><aside class="os-sidebar"><a class="os-brand" href="/?lang=ru"><span class="sa-logo"><span class="sa-logo-text">SA</span></span><span class="brand-copy"><b>SHARIPOV<span>AI</span></b><small>USERS</small></span></a><nav class="os-nav"><a href="/?lang=ru">Обзор</a><a href="/security?lang=ru">Кибер-безопасность</a><a class="active" href="/security/users">Пользователи</a><a href="/logout">Выйти</a></nav></aside><main class="os-main approved-shell"><section class="welcome-hero"><div><p class="eyebrow">USER MANAGEMENT</p><h1>Пользователи</h1><p>Админ может включать, отключать, менять роль и сбрасывать пароль пользователей.</p></div></section><section class="os-panel"><div class="panel-head"><h2>Список пользователей</h2><a href="/api/security/users">API</a></div><table class="trade-table"><thead><tr><th>Логин</th><th>Роль</th><th>Активен</th><th>Смена пароля</th><th>Создан</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""
        )

    @dashboard.get("/api/security/users")
    def users_api() -> dict[str, Any]:
        return {"status": "ok", "users": list_users(_load_users())}

    @dashboard.post("/api/security/users/{username}/disable")
    def disable_user(username: str, request: Request) -> dict[str, Any]:
        users_data = _load_users()
        result = set_user_active(users_data, username, False)
        if result["status"] == "ok":
            _save_users(users_data)
            _record_security_event("user_disabled", username, request, {"actor": _session_username(request) or "admin"})
        return result

    @dashboard.post("/api/security/users/{username}/enable")
    def enable_user(username: str, request: Request) -> dict[str, Any]:
        users_data = _load_users()
        result = set_user_active(users_data, username, True)
        if result["status"] == "ok":
            _save_users(users_data)
            _record_security_event("user_enabled", username, request, {"actor": _session_username(request) or "admin"})
        return result

    @dashboard.post("/api/security/users/{username}/promote")
    def promote_user(username: str, request: Request) -> dict[str, Any]:
        users_data = _load_users()
        result = set_user_role(users_data, username, "admin")
        if result["status"] == "ok":
            _save_users(users_data)
            _record_security_event("user_promoted", username, request, {"actor": _session_username(request) or "admin"})
        return result

    @dashboard.post("/api/security/users/{username}/demote")
    def demote_user(username: str, request: Request) -> dict[str, Any]:
        users_data = _load_users()
        result = set_user_role(users_data, username, "user")
        if result["status"] == "ok":
            _save_users(users_data)
            _record_security_event("user_demoted", username, request, {"actor": _session_username(request) or "admin"})
        return result

    @dashboard.post("/api/security/users/{username}/reset-password")
    def reset_password(username: str, request: Request) -> dict[str, Any]:
        users_data = _load_users()
        result = reset_user_password(users_data, username)
        if result["status"] == "ok":
            _save_users(users_data)
            _record_security_event("user_password_reset", username, request, {"actor": _session_username(request) or "admin"})
        return result

    return dashboard


def _user_row(user: dict[str, Any]) -> str:
    return f"<tr><td>{user['username']}</td><td>{user['role']}</td><td>{'Да' if user['active'] else 'Нет'}</td><td>{'Нужна' if user['must_change_password'] else 'Нет'}</td><td>{user['created_at']}</td></tr>"


app = create_user_admin_app()
