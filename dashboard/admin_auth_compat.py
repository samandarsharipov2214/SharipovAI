"""Compatibility guard for the configured local administrator.

A pending or inactive record in ``users.json`` must never shadow the explicitly
configured ``ADMIN_USERNAME``/``ADMIN_PASSWORD`` pair.  The configured
administrator is an operational break-glass account and is validated before
normal persisted users.  Session validation follows the same rule.
"""
from __future__ import annotations

import base64
import hmac
import importlib
import os
import time
from typing import Any


def install_admin_auth_compat() -> None:
    """Patch dashboard auth globals once, preserving normal user validation."""

    app_module = importlib.import_module("dashboard.app")
    if getattr(app_module, "_admin_auth_compat_installed", False):
        return

    original_valid_credentials = app_module._valid_credentials
    original_session_username = app_module._session_username

    def valid_credentials(username: str, password: str) -> bool:
        normalized = app_module._clean_username(username)
        admin_username = app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin"))
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        if admin_password and normalized == admin_username:
            return hmac.compare_digest(password, admin_password)
        return bool(original_valid_credentials(username, password))

    def session_username(request: Any) -> str | None:
        resolved = original_session_username(request)
        if resolved:
            return resolved

        raw = request.cookies.get(app_module.SESSION_COOKIE, "")
        if not raw:
            return None
        try:
            decoded = base64.urlsafe_b64decode(raw.encode())
            payload, signature = decoded.rsplit(b".", 1)
            expected = hmac.new(
                app_module._auth_secret().encode(),
                payload,
                app_module.hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                return None
            username, issued, _nonce = payload.decode().split(":", 2)
            normalized = app_module._clean_username(username)
            admin_username = app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin"))
            if normalized != admin_username:
                return None
            if int(time.time()) - int(issued) > app_module.SESSION_TTL_SECONDS:
                return None
            if not os.getenv("ADMIN_PASSWORD", ""):
                return None
            return normalized
        except Exception:
            return None

    app_module._valid_credentials = valid_credentials
    app_module._session_username = session_username
    app_module._admin_auth_compat_installed = True


__all__ = ["install_admin_auth_compat"]
