"""Security-enhanced SharipovAI dashboard entrypoint.

Run with:
    python -m uvicorn dashboard.secure_app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from runner import SharipovAIRunner

from .app import _clean_username, _login_page_html, _record_security_event, _safe_next_url, _valid_credentials, create_app
from .security_guard import DEFAULT_LOCK_SECONDS, DEFAULT_MAX_FAILED_ATTEMPTS, LoginAttemptGuard
from .user_admin import verify_password


def create_secure_app(runner_factory: Any | None = None) -> FastAPI:
    """Create dashboard app with login lockout protection enabled."""

    dashboard = create_app(runner_factory=runner_factory)
    dashboard.add_middleware(LoginLockoutMiddleware)

    @dashboard.get("/api/security/login-attempts")
    def login_attempts() -> dict[str, Any]:
        guard = login_attempt_guard()
        return {"status": "ok", "attempts": guard.snapshot()}

    return dashboard


def login_attempt_guard() -> LoginAttemptGuard:
    """Build login attempt guard from environment settings."""
    path = Path(os.getenv("AUTH_LOGIN_ATTEMPTS_FILE", "data/login_attempts.json"))
    max_failed_attempts = _int_env("AUTH_MAX_FAILED_ATTEMPTS", DEFAULT_MAX_FAILED_ATTEMPTS)
    lock_seconds = _int_env("AUTH_LOCK_SECONDS", DEFAULT_LOCK_SECONDS)
    return LoginAttemptGuard(path, max_failed_attempts=max_failed_attempts, lock_seconds=lock_seconds)


class LoginLockoutMiddleware:
    """Block brute-force login attempts before the login route runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/login" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        form = parse_qs(body.decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        next_url = _safe_next_url((form.get("next") or ["/"])[0])
        request = Request(scope)
        guard = login_attempt_guard()

        if guard.is_locked(username):
            seconds_left = guard.seconds_left(username)
            _record_security_event("login_blocked", username, request, {"seconds_left": seconds_left})
            await _html_login_error(scope, receive, send, next_url, f"Вход временно заблокирован. Осталось примерно {max(1, seconds_left // 60)} мин.", 423)
            return

        if not _valid_secure_credentials(username, password):
            result = guard.record_failure(username)
            _record_security_event("failed_login", username, request, {"reason": "bad_credentials", "failed_attempts": result.get("failed_attempts", 0)})
            if result.get("status") == "locked":
                _record_security_event("login_locked", username, request, {"locked_until": result.get("locked_until", 0)})
                await _html_login_error(scope, receive, send, next_url, "Слишком много неправильных попыток. Вход временно заблокирован.", 423)
                return
            await _html_login_error(scope, receive, send, next_url, "Неверный логин или пароль", 401)
            return

        guard.record_success(username)
        await self.app(scope, _replay_receive(body), send)


def _valid_secure_credentials(username: str, password: str) -> bool:
    if _valid_credentials(username, password):
        return True
    try:
        from . import stabilization_compat as compat

        user = compat._load_users().get(_clean_username(username), {})
        return bool(user.get("active")) and verify_password(password, str(user.get("password_hash", "")))
    except Exception:
        return False


async def _read_body(receive: Receive) -> bytes:
    body = b""
    more_body = True
    while more_body:
        message = await receive()
        body += message.get("body", b"")
        more_body = bool(message.get("more_body", False))
    return body


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


async def _html_login_error(scope: Scope, receive: Receive, send: Send, next_url: str, error: str, status_code: int) -> None:
    response: Response = HTMLResponse(_login_page_html(next_url=next_url, error=error), status_code=status_code)
    await response(scope, receive, send)


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


app = create_secure_app()
