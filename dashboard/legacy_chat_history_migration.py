"""Backfill legacy SaaS web-chat rows into canonical ProjectDatabase history.

This module is intentionally non-destructive: it reads ``saas_chat_messages`` and
appends deterministic message ids to ``project_messages``. Existing legacy rows
remain untouched so the migration can be retried or rolled back safely.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.project_database import ProjectDatabase

from .models_saas import ChatMessageLog, User

_PROJECT_ID = "sharipovai"
_CHANNEL = "web"


class LegacyChatMigrationError(RuntimeError):
    """Raised when a legacy row cannot be represented without losing meaning."""


def _created_at_ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.astimezone(UTC).timestamp() * 1000)


def _metadata(message: ChatMessageLog, user: User) -> dict[str, Any]:
    base: dict[str, Any] = {
        "channel": _CHANNEL,
        "legacy_source_table": "saas_chat_messages",
        "legacy_message_id": str(message.id),
        "source": str(message.source or "gemini"),
    }
    if message.request_id:
        base["request_id"] = str(message.request_id)
    if message.model_name:
        base["model_name"] = str(message.model_name)

    if message.role == "user":
        base.update(
            actor_id=str(user.id),
            actor_email=str(user.email),
            actor_type="user",
        )
    elif message.role == "assistant":
        base.update(
            actor_id="system-gemini",
            actor_type="system",
        )
    else:
        raise LegacyChatMigrationError(
            f"unsupported legacy chat role {message.role!r} for message {message.id}"
        )
    return base


def backfill_legacy_web_chat_history(
    db: Session,
    *,
    database: ProjectDatabase | None = None,
    batch_size: int = 500,
) -> dict[str, int]:
    """Copy legacy web-chat rows to canonical history without deleting legacy data.

    Message ids are derived from immutable legacy primary keys, so rerunning the
    migration is idempotent. Rows are streamed in bounded batches and original
    timestamps are preserved for deterministic conversation ordering.
    """

    batch_size = min(max(int(batch_size), 1), 5_000)
    project_db = database or ProjectDatabase()
    project_db.initialize()

    statement = (
        select(ChatMessageLog, User)
        .join(User, ChatMessageLog.user_id == User.id)
        .order_by(ChatMessageLog.created_at.asc(), ChatMessageLog.id.asc())
    )

    attempted = 0
    users: set[str] = set()
    result = db.execute(statement).yield_per(batch_size)
    for message, user in result:
        content = str(message.content or "")
        if not content.strip():
            raise LegacyChatMigrationError(
                f"empty legacy chat content for message {message.id}"
            )
        project_db.append_message(
            project_id=_PROJECT_ID,
            chat_id=f"web-{str(user.id).strip()}",
            message_id=f"legacy-web-{str(message.id).strip()}",
            role=str(message.role),
            content=content,
            metadata=_metadata(message, user),
            created_at_ms=_created_at_ms(message.created_at),
        )
        attempted += 1
        users.add(str(user.id))

    return {
        "legacy_rows_attempted": attempted,
        "users_seen": len(users),
    }


__all__ = [
    "LegacyChatMigrationError",
    "backfill_legacy_web_chat_history",
]
