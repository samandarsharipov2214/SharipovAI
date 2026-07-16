"""Reload-safe compatibility for the configured administrator.

The explicit ``ADMIN_USERNAME``/``ADMIN_PASSWORD`` account is the break-glass
administrator. A pending or inactive persisted user with the same normalized name
must never shadow it. The compatibility functions are reinstalled before every app
factory call because legacy tests reload ``dashboard.app`` in-place.
"""
from __future__ import annotations

import base64
import hmac
import importlib
import os
import time
from functools import wraps
from typing import Any, Callable

_COMPAT_MARKER = "_sharipovai_admin_auth_compat"
_MAX_CLOCK_SKEW_SECONDS = 60


def _configured_admin(app_module: Any) -> tuple[str, str]:
    return (
        app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin")),
        os.getenv("ADMIN_PASSWORD", ""),
    )


def _valid_credentials(app_module: Any, username: str, password: str) -> bool:
    normalized = app_module._clean_username(username)
    admin_username, admin_password = _configured_admin(app_module)
    if admin_password and normalized == admin_username:
        return hmac.compare_digest(str(password), admin_password)

    user = app_module._user_record(app_module._load_users(), normalized)
    if not user:
        return False
    if not bool(user.get("active", True)):
        return False
    if str(user.get("role", "user")).lower() not in {"admin", "user"}:
        return False
    return bool(
        app_module.verify_password(
            str(password),
            str(user.get("password_hash", "")),
        )
    )


def _session_username(app_module: Any, request: Any) -> str | None:
    raw = str(request.cookies.get(app_module.SESSION_COOKIE, "") or "")
    if not raw:
        return None
    try:
        padding = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
        payload, signature = decoded.rsplit(b".", 1)
        expected = hmac.new(
            app_module._auth_secret().encode("utf-8"),
            payload,
            app_module.hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        username, issued_raw, _nonce = payload.decode("utf-8").split(":", 2)
        age = int(time.time()) - int(issued_raw)
        if age < -_MAX_CLOCK_SKEW_SECONDS or age > int(app_module.SESSION_TTL_SECONDS):
            return None

        normalized = app_module._clean_username(username)
        admin_username, admin_password = _configured_admin(app_module)
        if admin_password and normalized == admin_username:
            return normalized

        user = app_module._user_record(app_module._load_users(), normalized)
        if not user:
            return normalized
        if not bool(user.get("active", True)):
            return None
        if str(user.get("role", "")).lower() not in {"admin", "user"}:
            return None
        return normalized
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        return None


def _original(callable_obj: Callable[..., Any]) -> Callable[..., Any]:
    return getattr(callable_obj, "__sharipovai_original__", callable_obj)


def _install_function_wrappers(app_module: Any) -> None:
    def valid_credentials(username: str, password: str) -> bool:
        current = importlib.import_module("dashboard.app")
        return _valid_credentials(current, username, password)

    def session_username(request: Any) -> str | None:
        current = importlib.import_module("dashboard.app")
        return _session_username(current, request)

    setattr(valid_credentials, _COMPAT_MARKER, True)
    setattr(session_username, _COMPAT_MARKER, True)
    app_module._valid_credentials = valid_credentials
    app_module._session_username = session_username
    app_module._admin_auth_compat_installed = True


def install_admin_auth_compat(*, force: bool = False) -> None:
    """Install authoritative auth functions and a reload-safe app factory wrapper."""

    app_module = importlib.import_module("dashboard.app")
    if force or not (
        getattr(app_module._valid_credentials, _COMPAT_MARKER, False)
        and getattr(app_module._session_username, _COMPAT_MARKER, False)
    ):
        _install_function_wrappers(app_module)

    current_create_app = app_module.create_app
    if getattr(current_create_app, _COMPAT_MARKER, False):
        return
    original_create_app = _original(current_create_app)

    @wraps(original_create_app)
    def create_app(*args: Any, **kwargs: Any):
        current = importlib.import_module("dashboard.app")
        _install_function_wrappers(current)
        instance = original_create_app(*args, **kwargs)
        instance._session_username = current._session_username
        return instance

    setattr(create_app, _COMPAT_MARKER, True)
    setattr(create_app, "__sharipovai_original__", original_create_app)
    app_module.create_app = create_app


__all__ = ["install_admin_auth_compat"]
