"""Role helpers for SharipovAI access control."""

from __future__ import annotations

import os
from typing import Any


def clean_username(username: str | None) -> str:
    """Normalize username for comparisons."""
    return (username or "").strip().lower()


def resolve_role(username: str | None, users_data: dict[str, Any]) -> str | None:
    """Resolve a user role from admin settings or stored users.

    Both historical ``{"users": {...}}`` and current flat ``{username: {...}}``
    stores are supported so auth migrations do not break the admin UI.
    """
    clean = clean_username(username)
    if not clean:
        return None

    admin_username = clean_username(os.getenv("ADMIN_USERNAME", "Samandar2212"))
    if clean == admin_username:
        return "admin"

    container = users_data.get("users") if isinstance(users_data.get("users"), dict) else users_data
    user = container.get(clean) if isinstance(container, dict) else None
    if isinstance(user, dict):
        return str(user.get("role", "user"))
    return None


def is_admin(username: str | None, users_data: dict[str, Any]) -> bool:
    """Return whether the user is an admin."""
    return resolve_role(username, users_data) == "admin"
