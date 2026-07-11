"""Unify legacy and canonical authentication storage and session resolution.

Older local tools and tests use ``AUTH_*_FILE`` while the current dashboard uses
``SHARIPOVAI_*_FILE``. Resolving them in different modules created split-brain
authentication: login could read one users file while the signed-session verifier
read another. This adapter installs one dynamic resolver for both code paths.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import os
import time
from pathlib import Path
from typing import Any, Callable

_INSTALLED = False
_HMAC_DIGEST_SIZE = hashlib.sha256().digest_size


def _resolved_path(
    legacy_name: str,
    canonical_name: str,
    default_factory: Callable[[], Path],
) -> Path:
    """Resolve an explicit legacy alias first, then the canonical name."""

    legacy = os.getenv(legacy_name, "").strip()
    if legacy:
        return Path(legacy)
    canonical = os.getenv(canonical_name, "").strip()
    if canonical:
        return Path(canonical)
    return default_factory()


def _unquote_cookie_value(value: str) -> str:
    """Remove one valid outer quote pair added by HTTP cookie serialization."""

    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"\"", "'"}:
        return normalized[1:-1]
    return normalized


def _decode_legacy_session(raw: str) -> tuple[bytes, bytes] | None:
    """Decode ``base64(payload + '.' + sha256_hmac)`` without ambiguous splitting.

    The original format stores a raw binary HMAC after the separator. A raw HMAC
    may itself contain ``b'.'``, so ``rsplit`` is incorrect. SHA-256 signatures
    are always 32 bytes; therefore the separator is exactly byte ``-33``.
    """

    try:
        decoded = base64.urlsafe_b64decode(raw.encode())
    except Exception:
        return None
    minimum_size = _HMAC_DIGEST_SIZE + 2
    if len(decoded) < minimum_size:
        return None
    separator_index = len(decoded) - _HMAC_DIGEST_SIZE - 1
    if decoded[separator_index:separator_index + 1] != b".":
        return None
    payload = decoded[:separator_index]
    signature = decoded[separator_index + 1:]
    if len(signature) != _HMAC_DIGEST_SIZE:
        return None
    return payload, signature


def install_auth_storage_aliases() -> None:
    """Install shared path and signed-session resolvers exactly once."""

    global _INSTALLED
    if _INSTALLED:
        return

    app_module = importlib.import_module("dashboard.app")
    compat_module = importlib.import_module("dashboard.stabilization_compat")

    def users_file() -> Path:
        return _resolved_path(
            "AUTH_USERS_FILE",
            "SHARIPOVAI_USERS_FILE",
            lambda: app_module._data_dir() / "users.json",
        )

    def access_requests_file() -> Path:
        return _resolved_path(
            "AUTH_ACCESS_REQUESTS_FILE",
            "SHARIPOVAI_ACCESS_REQUESTS_FILE",
            lambda: app_module._data_dir() / "access_requests.json",
        )

    def security_events_file() -> Path:
        return _resolved_path(
            "AUTH_SECURITY_EVENTS_FILE",
            "SHARIPOVAI_SECURITY_EVENTS_FILE",
            lambda: app_module._data_dir() / "security_events.jsonl",
        )

    def session_username(request: Any) -> str | None:
        """Validate the signed cookie against the shared users store."""

        raw = _unquote_cookie_value(
            request.cookies.get(app_module.SESSION_COOKIE, "")
        )
        if not raw:
            return None
        decoded = _decode_legacy_session(raw)
        if decoded is None:
            return None
        payload, signature = decoded
        try:
            expected = hmac.new(
                app_module._auth_secret().encode(),
                payload,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                return None

            username, issued, _nonce = payload.decode().split(":", 2)
            if int(time.time()) - int(issued) > app_module.SESSION_TTL_SECONDS:
                return None

            clean_username = app_module._clean_username(username)
            configured_admin = app_module._clean_username(
                os.getenv("ADMIN_USERNAME", "admin")
            )
            if clean_username == configured_admin:
                return clean_username

            user = app_module._user_record(app_module._load_users(), clean_username)
            if user and (
                not bool(user.get("active", True))
                or str(user.get("role", "")) not in {"admin", "user"}
            ):
                return None
            return clean_username
        except Exception:
            return None

    app_module._users_file = users_file
    app_module._access_requests_file = access_requests_file
    app_module._security_events_file = security_events_file
    app_module._session_username = session_username

    compat_module._compat_users_file = users_file
    compat_module._compat_requests_file = access_requests_file
    compat_module._compat_events_file = security_events_file

    _INSTALLED = True


__all__ = ["install_auth_storage_aliases"]
