"""Passive bridge from canonical Learning Engine evidence to Memory Layer L0."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from storage import ProjectDatabase

from .service import MemoryService


class DevelopmentLearningMemoryBridge:
    """Copy meaningful learning evidence; never modifies the Learning Engine."""

    namespace = "development_learning_events"

    def __init__(self, service: MemoryService, database: ProjectDatabase | None = None) -> None:
        self.service = service
        self.database = database or service.database

    def collect_once(self, *, limit: int = 200) -> dict[str, Any]:
        if not self.service.enabled:
            return {"status": "disabled", "seen": 0, "recorded": 0}
        events = list(reversed(self.database.list_events(self.namespace, limit=min(max(limit, 1), 1000))))
        recorded = 0
        for event in events:
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            source_ref = f"project_event:{event.get('event_id', '')}"
            message = json.dumps(
                {
                    "event_type": event.get("entity_type"),
                    "entity_id": event.get("entity_id"),
                    "payload": payload,
                    "created_at_ms": event.get("created_at_ms"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            result = self.service.record_dialog(
                team_id=self.service.settings.team_id,
                user_id=self.service.settings.user_id,
                agent_id="learning_engine",
                session_id=str(event.get("entity_id") or "development_learning"),
                message=message,
                source_ref=source_ref,
                role="event",
                metadata={
                    "origin_namespace": self.namespace,
                    "origin_event_id": event.get("event_id"),
                    "passive_collection": True,
                },
                created_at_ms=int(event.get("created_at_ms") or 0) or None,
            )
            if result is not None:
                recorded += 1
        return {"status": "ok", "seen": len(events), "recorded": recorded}


__all__ = ["DevelopmentLearningMemoryBridge"]
