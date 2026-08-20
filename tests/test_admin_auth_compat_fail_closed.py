from __future__ import annotations

import base64
import hashlib
import hmac
import time
from types import SimpleNamespace

from dashboard.admin_auth_compat import _session_username


SECRET = "test-auth-secret"
COOKIE = "sharipovai_session"


def _app(users: dict[str, dict[str, object]]):
    return SimpleNamespace(
        SESSION_COOKIE=COOKIE,
        SESSION_TTL_SECONDS=3600,
        hashlib=hashlib,
        _auth_secret=lambda: SECRET,
        _clean_username=lambda value: str(value).strip().lower(),
        _load_users=lambda: users,
        _user_record=lambda records, username: records.get(username),
    )


def _request(username: str):
    payload = f"{username}:{int(time.time())}:nonce".encode("utf-8")
    signature = hmac.new(SECRET.encode("utf-8"), payload, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(payload + b"." + signature).decode("ascii").rstrip("=")
    return SimpleNamespace(cookies={COOKIE: token})


def test_signed_session_for_deleted_user_is_denied(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")

    assert _session_username(_app({}), _request("deleted-user")) is None


def test_signed_session_for_inactive_user_is_denied(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    users = {"admin-user": {"active": False, "role": "admin"}}

    assert _session_username(_app(users), _request("admin-user")) is None


def test_signed_session_for_active_admin_is_preserved(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "break-glass-admin")
    users = {"admin-user": {"active": True, "role": "admin"}}

    assert _session_username(_app(users), _request("admin-user")) == "admin-user"


def test_configured_break_glass_admin_remains_available(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "configured-secret")

    assert _session_username(_app({}), _request("admin")) == "admin"
