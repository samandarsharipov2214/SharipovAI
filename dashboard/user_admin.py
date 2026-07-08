"""Admin user-management service for SharipovAI."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any


PBKDF2_ITERATIONS = 120_000
ALLOWED_ROLES = {"admin", "user"}


def list_users(users_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return safe user summaries without password hashes."""

    users = users_data.get("users", {})
    if not isinstance(users, dict):
        return []
    result: list[dict[str, Any]] = []
    for username, record in sorted(users.items()):
        if not isinstance(record, dict):
            continue
        result.append(
            {
                "username": str(username),
                "role": str(record.get("role", "user")),
                "active": bool(record.get("active", True)),
                "must_change_password": bool(record.get("must_change_password", False)),
                "created_at": int(record.get("created_at", 0) or 0),
                "password_changed_at": int(record.get("password_changed_at", 0) or 0),
                "disabled_at": int(record.get("disabled_at", 0) or 0),
            }
        )
    return result


def set_user_active(users_data: dict[str, Any], username: str, active: bool) -> dict[str, Any]:
    """Enable or disable a user."""

    user = _get_user(users_data, username)
    if user is None:
        return {"status": "not_found", "username": username}
    user["active"] = active
    if active:
        user.pop("disabled_at", None)
    else:
        user["disabled_at"] = int(time.time())
    return {"status": "ok", "username": _clean(username), "active": active}


def set_user_role(users_data: dict[str, Any], username: str, role: str) -> dict[str, Any]:
    """Change user role."""

    role = role.strip().lower()
    if role not in ALLOWED_ROLES:
        return {"status": "invalid_role", "username": username, "role": role}
    user = _get_user(users_data, username)
    if user is None:
        return {"status": "not_found", "username": username}
    user["role"] = role
    user["role_changed_at"] = int(time.time())
    return {"status": "ok", "username": _clean(username), "role": role}


def reset_user_password(users_data: dict[str, Any], username: str) -> dict[str, Any]:
    """Reset a user password and require a change on next login."""

    user = _get_user(users_data, username)
    if user is None:
        return {"status": "not_found", "username": username}
    temporary_password = generate_temporary_password()
    user["password_hash"] = hash_password(temporary_password)
    user["must_change_password"] = True
    user["password_reset_at"] = int(time.time())
    user["active"] = True
    return {"status": "ok", "username": _clean(username), "temporary_password": temporary_password}


def create_user(users_data: dict[str, Any], username: str, password: str, *, role: str = "user", must_change_password: bool = True) -> dict[str, Any]:
    """Create a local user in a users_data dict."""

    clean = _clean(username)
    if not clean:
        return {"status": "invalid_username", "username": username}
    if role not in ALLOWED_ROLES:
        return {"status": "invalid_role", "username": clean, "role": role}
    users = users_data.setdefault("users", {})
    if clean in users:
        return {"status": "already_exists", "username": clean}
    users[clean] = {
        "password_hash": hash_password(password),
        "created_at": int(time.time()),
        "active": True,
        "role": role,
        "must_change_password": must_change_password,
    }
    return {"status": "ok", "username": clean, "role": role}


def generate_temporary_password() -> str:
    """Generate a readable temporary password marker."""

    return f"SA-{secrets.token_hex(6)}"


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256."""

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a PBKDF2-SHA256 password hash."""

    try:
        algorithm, iterations_text, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations_text)).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _get_user(users_data: dict[str, Any], username: str) -> dict[str, Any] | None:
    users = users_data.setdefault("users", {})
    user = users.get(_clean(username))
    return user if isinstance(user, dict) else None


def _clean(username: str) -> str:
    return username.strip().lower()
