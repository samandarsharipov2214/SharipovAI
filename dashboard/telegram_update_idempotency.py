"""Persistent idempotency guard for Telegram webhook update IDs."""
from __future__ import annotations

from typing import Any

from storage.project_database import ProjectDatabase

_NAMESPACE = "telegram_webhook"
_ENTITY_TYPE = "update"


def claim_telegram_update(update_id: int, *, database: ProjectDatabase | None = None) -> bool:
    """Atomically claim a Telegram update ID in the canonical project database.

    Returns ``True`` for the first claimant and ``False`` for a persisted duplicate.
    Database failures remain fail-closed and are re-raised.
    """

    parsed_update_id = int(update_id)
    if parsed_update_id < 0:
        raise ValueError("update_id must be non-negative")

    db = database or ProjectDatabase()
    db.initialize()
    event_id = f"telegram_update:{parsed_update_id}"
    entity_id = str(parsed_update_id)
    payload: dict[str, Any] = {"update_id": parsed_update_id, "status": "claimed"}

    try:
        db.append_event(
            _NAMESPACE,
            _ENTITY_TYPE,
            entity_id,
            payload,
            event_id=event_id,
        )
        return True
    except Exception:
        # A duplicate event_id is the expected contention path. Confirm it from
        # canonical storage before suppressing the exception; all other database
        # failures remain fail-closed.
        events = db.list_events(
            _NAMESPACE,
            entity_type=_ENTITY_TYPE,
            entity_id=entity_id,
            limit=10,
        )
        if any(event.get("event_id") == event_id for event in events):
            return False
        raise
