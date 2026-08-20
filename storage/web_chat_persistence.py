"""Canonical persistence adapter for authenticated Web2 chat completions.

The legacy SaaS chat log remains a compatibility/billing record for now, but
conversation history is also written to the shared ``ProjectDatabase`` message
store so Web2 can converge with Telegram and Mini App on one canonical history.
Writes use deterministic message ids and are therefore retry-idempotent.
"""
from __future__ import annotations

from typing import Any

from storage.project_database import ProjectDatabase

_PROJECT_ID = "sharipovai"
_CHANNEL = "web"


def persist_web_chat_completion(
    *,
    user_id: str,
    user_email: str,
    user_message: str,
    assistant_message: str,
    model_name: str,
    request_id: str,
    database: ProjectDatabase | None = None,
) -> None:
    """Append one user/assistant exchange to canonical conversation history.

    ``request_id`` is already generated once per provider request. Reusing it to
    derive both message ids makes retries idempotent because ``ProjectDatabase``
    ignores duplicate ``message_id`` inserts.
    """

    db = database or ProjectDatabase()
    db.initialize()
    chat_id = f"web-{str(user_id).strip()}"
    base_metadata: dict[str, Any] = {
        "channel": _CHANNEL,
        "request_id": str(request_id),
        "model_name": str(model_name),
        "provider": "gemini",
    }
    db.append_message(
        project_id=_PROJECT_ID,
        chat_id=chat_id,
        message_id=f"web-{request_id}-user",
        role="user",
        content=user_message,
        metadata={
            **base_metadata,
            "actor_id": str(user_id),
            "actor_email": str(user_email),
            "actor_type": "user",
        },
    )
    db.append_message(
        project_id=_PROJECT_ID,
        chat_id=chat_id,
        message_id=f"web-{request_id}-assistant",
        role="assistant",
        content=assistant_message,
        metadata={
            **base_metadata,
            "actor_id": "system-gemini",
            "actor_type": "system",
        },
    )


__all__ = ["persist_web_chat_completion"]
