"""Canonical Telegram identity binding for SharipovAI Mini App authentication."""
from __future__ import annotations

from dataclasses import dataclass

from storage.project_database import ProjectDatabase, VersionConflict

_NAMESPACE = "telegram_identity"
_PROVIDER = "telegram"


class TelegramIdentityConflict(RuntimeError):
    """Raised when a Telegram subject is already bound to a different user."""


@dataclass(frozen=True)
class TelegramIdentityBinding:
    telegram_user_id: int
    canonical_user_id: int


def _telegram_key(telegram_user_id: int) -> str:
    parsed = int(telegram_user_id)
    if parsed <= 0:
        raise ValueError("telegram_user_id must be positive")
    return f"telegram:{parsed}"


def get_telegram_identity_binding(
    telegram_user_id: int,
    *,
    database: ProjectDatabase | None = None,
) -> TelegramIdentityBinding | None:
    """Resolve a Telegram subject from canonical project storage."""

    parsed = int(telegram_user_id)
    key = _telegram_key(parsed)
    db = database or ProjectDatabase()
    db.initialize()
    stored = db.get_json(_NAMESPACE, key)
    if stored is None:
        return None
    value = stored.get("value")
    if not isinstance(value, dict):
        raise RuntimeError("telegram identity binding is malformed")
    if value.get("provider") != _PROVIDER or int(value.get("telegram_user_id", 0)) != parsed:
        raise RuntimeError("telegram identity binding provenance mismatch")
    canonical_user_id = int(value.get("canonical_user_id", 0))
    if canonical_user_id <= 0:
        raise RuntimeError("telegram identity binding has invalid canonical user")
    return TelegramIdentityBinding(parsed, canonical_user_id)


def bind_telegram_identity(
    telegram_user_id: int,
    canonical_user_id: int,
    *,
    database: ProjectDatabase | None = None,
) -> TelegramIdentityBinding:
    """Bind once without allowing a Telegram subject to be silently reassigned."""

    parsed_telegram_id = int(telegram_user_id)
    parsed_user_id = int(canonical_user_id)
    if parsed_user_id <= 0:
        raise ValueError("canonical_user_id must be positive")
    key = _telegram_key(parsed_telegram_id)
    db = database or ProjectDatabase()
    db.initialize()

    existing = get_telegram_identity_binding(parsed_telegram_id, database=db)
    if existing is not None:
        if existing.canonical_user_id != parsed_user_id:
            raise TelegramIdentityConflict("telegram identity is already bound")
        return existing

    value = {
        "provider": _PROVIDER,
        "telegram_user_id": parsed_telegram_id,
        "canonical_user_id": parsed_user_id,
    }
    try:
        db.put_json(_NAMESPACE, key, value, expected_version=0)
    except VersionConflict:
        # Another request may have won the first-write race. Re-read canonical
        # state and accept it only when it points to the same user.
        raced = get_telegram_identity_binding(parsed_telegram_id, database=db)
        if raced is None or raced.canonical_user_id != parsed_user_id:
            raise TelegramIdentityConflict("telegram identity is already bound")
        return raced
    return TelegramIdentityBinding(parsed_telegram_id, parsed_user_id)


__all__ = [
    "TelegramIdentityBinding",
    "TelegramIdentityConflict",
    "bind_telegram_identity",
    "get_telegram_identity_binding",
]
