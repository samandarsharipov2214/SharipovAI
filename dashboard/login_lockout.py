"""Brute-force protection shared by every SharipovAI dashboard entrypoint."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .security_guard import DEFAULT_LOCK_SECONDS, DEFAULT_MAX_FAILED_ATTEMPTS, LoginAttemptGuard


def login_attempt_guard() -> LoginAttemptGuard:
    path = Path(os.getenv("AUTH_LOGIN_ATTEMPTS_FILE", str(_data_dir() / "login_attempts.json")))
    return LoginAttemptGuard(
        path,
        max_failed_attempts=_positive_int("AUTH_MAX_FAILED_ATTEMPTS", DEFAULT_MAX_FAILED_ATTEMPTS),
        lock_seconds=_positive_int("AUTH_LOCK_SECONDS", DEFAULT_LOCK_SECONDS),
    )


def install_login_lockout(app: FastAPI) -> None:
    """Install lockout middleware and diagnostics exactly once on an app."""
    if getattr(app.state, "login_lockout_installed", False):
        return
    app.state.login_lockout_installed = True
    app.add_middleware(LoginLockoutMiddleware)

    @app.get("/api/security/login-attempts")
    def login_attempts(request: Request) -> dict[str, Any]:
        from .app import _is_admin_request

        if not _is_admin_request(request) and os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}:
            return {"status": "forbidden", "attempts": {"users": {}}}
        return {"status": "ok", "attempts": login_attempt_guard().snapshot()}


class LoginLockoutMiddleware:
    """Reject repeated invalid login attempts before the route creates a session."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/login" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        from .app import (
            _clean_username,
            _login_page_html,
            _record_security_event,
            _safe_next_url,
            _valid_credentials,
        )

        body = await _read_body(receive)
        form = parse_qs(body.decode("utf-8", errors="replace"))
        username = _clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        next_url = _safe_next_url((form.get("next") or ["/"])[0])
        request = Request(scope)
        guard = login_attempt_guard()

        if guard.is_locked(username):
            seconds_left = guard.seconds_left(username)
            _record_security_event("login_blocked", username or "anonymous", request, {"seconds_left": seconds_left})
            await _error(scope, send, _login_page_html, next_url, "Вход временно заблокирован. Повторите позже.", 423)
            return

        if not _valid_credentials(username, password):
            result = guard.record_failure(username or "anonymous")
            _record_security_event(
                "failed_login",
                username or "anonymous",
                request,
                {"reason": "bad_credentials", "failed_attempts": result.get("failed_attempts", 0)},
            )
            if result.get("status") == "locked":
                await _error(scope, send, _login_page_html, next_url, "Слишком много неправильных попыток. Вход временно заблокирован.", 423)
                return
            await _error(scope, send, _login_page_html, next_url, "Неверный логин, пароль или доступ ещё не одобрен", 401)
            return

        guard.record_success(username)
        await self.app(scope, _replay_receive(body), send)


async def _read_body(receive: Receive) -> bytes:
    body = b""
    more = True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = bool(message.get("more_body", False))
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


async def _error(scope: Scope, send: Send, renderer: Any, next_url: str, message: str, status: int) -> None:
    response: Response = HTMLResponse(renderer(next_url=next_url, error=message), status_code=status)
    await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def _data_dir() -> Path:
    return Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


__all__ = ["LoginLockoutMiddleware", "install_login_lockout", "login_attempt_guard"]
