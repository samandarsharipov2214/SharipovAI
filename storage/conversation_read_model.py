"""Read-only conversation views over the canonical ProjectDatabase message store.

This module deliberately does not create another conversation table or persistence
backend. Conversation identity is the existing ``(project_id, chat_id)`` pair in
``project_messages``; all history reads delegate to :class:`ProjectDatabase`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from storage.project_database import ProjectDatabase


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """Derived summary for one canonical chat conversation."""

    project_id: str
    chat_id: str
    message_count: int
    first_message_at_ms: int
    last_message_at_ms: int
    last_role: str
    last_content: str


@dataclass(frozen=True, slots=True)
class ConversationIndex:
    """Bounded conversation index derived from canonical stored messages.

    ``scan_truncated`` is conservative: when the configured scan limit is
    reached, callers must not claim that the index contains every historical
    conversation. This keeps bounded reads fail-closed instead of silently
    presenting a partial index as complete.
    """

    conversations: tuple[ConversationSummary, ...]
    scan_truncated: bool
    scanned_message_count: int


class ConversationReadModel:
    """Build conversation views without introducing a second source of truth."""

    def __init__(self, database: ProjectDatabase) -> None:
        self.database = database

    def list_conversations(
        self,
        *,
        project_id: str,
        limit: int = 100,
        message_scan_limit: int = 2000,
    ) -> ConversationIndex:
        """Return recent conversation summaries from canonical messages.

        The underlying ``ProjectDatabase.list_messages`` API is intentionally
        bounded to 2,000 messages. If that boundary is reached, ``scan_truncated``
        is true so consumers cannot mistake a bounded projection for complete
        history.
        """

        conversation_limit = min(max(int(limit), 1), 1000)
        scan_limit = min(max(int(message_scan_limit), 1), 2000)
        messages = self.database.list_messages(project_id=project_id, limit=scan_limit)

        grouped: dict[str, dict[str, Any]] = {}
        for message in messages:
            chat_id = str(message["chat_id"])
            timestamp = int(message["created_at_ms"])
            current = grouped.get(chat_id)
            if current is None:
                grouped[chat_id] = {
                    "project_id": str(message["project_id"]),
                    "chat_id": chat_id,
                    "message_count": 1,
                    "first_message_at_ms": timestamp,
                    "last_message_at_ms": timestamp,
                    "last_role": str(message["role"]),
                    "last_content": str(message["content"]),
                    "last_message_id": str(message["message_id"]),
                }
                continue

            current["message_count"] += 1
            current["first_message_at_ms"] = min(int(current["first_message_at_ms"]), timestamp)
            last_key = (int(current["last_message_at_ms"]), str(current["last_message_id"]))
            message_key = (timestamp, str(message["message_id"]))
            if message_key >= last_key:
                current["last_message_at_ms"] = timestamp
                current["last_role"] = str(message["role"])
                current["last_content"] = str(message["content"])
                current["last_message_id"] = str(message["message_id"])

        ordered = sorted(
            grouped.values(),
            key=lambda item: (int(item["last_message_at_ms"]), str(item["chat_id"])),
            reverse=True,
        )[:conversation_limit]
        summaries = tuple(
            ConversationSummary(
                project_id=str(item["project_id"]),
                chat_id=str(item["chat_id"]),
                message_count=int(item["message_count"]),
                first_message_at_ms=int(item["first_message_at_ms"]),
                last_message_at_ms=int(item["last_message_at_ms"]),
                last_role=str(item["last_role"]),
                last_content=str(item["last_content"]),
            )
            for item in ordered
        )
        return ConversationIndex(
            conversations=summaries,
            scan_truncated=len(messages) >= scan_limit,
            scanned_message_count=len(messages),
        )

    def get_history(
        self,
        *,
        project_id: str,
        chat_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return canonical ordered history for exactly one chat."""

        return self.database.list_messages(project_id=project_id, chat_id=chat_id, limit=limit)
