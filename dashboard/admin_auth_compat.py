"""Import-order-safe compatibility for the configured administrator.

A pending/inactive ``users.json`` record must never shadow the explicit
``ADMIN_USERNAME``/``ADMIN_PASSWORD`` break-glass account.  The compatibility
layer is deliberately installed both at package import and before every new
``create_app()`` call so module reloads and legacy factories cannot silently
restore the old ordering.
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
    username = app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin"))
    password = os.getenv("ADMIN_PASSWORD", "")
    return username, password


def _decode_admin_session(app_module: Any, request: Any) -> str | None:
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
        issued = int(issued_raw)
        age = int(time.time()) - issued
        if age < -_MAX_CLOCK_SKEW_SECONDS or age > int(app_module.SESSION_TTL_SECONDS):
            return None
        normalized = app_module._clean_username(username)
        admin_username, admin_password = _configured_admin(app_module)
        if not admin_password or normalized != admin_username:
            return None
        return normalized
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        return None


def _original(callable_obj: Callable[..., Any]) -> Callable[..., Any]:
    return getattr(callable_obj, "__sharipovai_original__", callable_obj)


def _install_function_wrappers(app_module: Any) -> None:
    current_credentials = app_module._valid_credentials
    current_session = app_module._session_username
    if getattr(current_credentials, _COMPAT_MARKER, False) and getattr(current_session, _COMPAT_MARKER, False):
        return

    original_valid_credentials = _original(current_credentials)
    original_session_username = _original(current_session)

    @wraps(original_valid_credentials)
    def valid_credentials(username: str, password: str) -> bool:
        normalized = app_module._clean_username(username)
        admin_username, admin_password = _configured_admin(app_module)
        if admin_password and normalized == admin_username:
            return hmac.compare_digest(str(password), admin_password)
        return bool(original_valid_credentials(username, password))

    @wraps(original_session_username)
    def session_username(request: Any) -> str | None:
        resolved = original_session_username(request)
        if resolved:
            return resolved
        return _decode_admin_session(app_module, request)

    setattr(valid_credentials, _COMPAT_MARKER, True)
    setattr(valid_credentials, "__sharipovai_original__", original_valid_credentials)
    setattr(session_username, _COMPAT_MARKER, True)
    setattr(session_username, "__sharipovai_original__", original_session_username)
    app_module._valid_credentials = valid_credentials
    app_module._session_username = session_username
    app_module._admin_auth_compat_installed = True


def install_admin_auth_compat() -> None:
    """Install wrappers and make every future app factory call re-check them."""

    app_module = importlib.import_module("dashboard.app")
    _install_function_wrappers(app_module)

    current_create_app = app_module.create_app
    if getattr(current_create_app, _COMPAT_MARKER, False):
        return
    original_create_app = _original(current_create_app)

    @wraps(original_create_app)
    def create_app(*args: Any, **kwargs: Any):
        _install_function_wrappers(app_module)
        instance = original_create_app(*args, **kwargs)
        # Legacy middleware tests used an app-local session resolver.  Expose the
        # canonical resolver without making it authoritative over the module.
        if not hasattr(instance, "_session_username"):
            instance._session_username = app_module._session_username
        return instance

    setattr(create_app, _COMPAT_MARKER, True)
    setattr(create_app, "__sharipovai_original__", original_create_app)
    app_module.create_app = create_app


__all__ = ["install_admin_auth_compat"]
