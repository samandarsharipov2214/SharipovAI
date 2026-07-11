"""Central memory, events and summaries for the existing News Intelligence network.

ProjectDatabase is the source of truth. RAM deques remain bounded read caches so
restarts no longer erase article evidence or AI events.
"""
from __future__ import annotations

import math
import os
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

from storage import ProjectDatabase, VersionConflict, list_json_items

from .agents import SourceAgent
from .models import NewsArticle, NewsEnvelope, SourceFetch


@dataclass(frozen=True, slots=True)
class HubIngestResult:
    accepted: int
    duplicates: int
    memory_size: int
    critical_count: int
    high_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "memory_size": self.memory_size,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
        }


class NewsHub:
    def __init__(self, *, database: ProjectDatabase | None = None) -> None:
        self.database = database
        if self.database is not None:
            self.database.initialize()
        memory_limit = _bounded_int("NEWS_AGENT_MEMORY_LIMIT", default=500, minimum=50, maximum=5000)
        event_limit = _bounded_int("NEWS_AGENT_EVENT_LIMIT", default=1000, minimum=100, maximum=10000)
        self._memory: deque[NewsEnvelope] = deque(maxlen=memory_limit)
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self.memory_namespace = "news_memory"
        self.event_namespace = "news_events"
        self._restore()

    def ingest(self, agent: SourceAgent, articles: list[NewsArticle], fetched: SourceFetch) -> HubIngestResult:
        accepted = 0
        duplicates = 0
        critical = 0
        high = 0
        for article in articles:
            envelope = agent.register(article, fetched)
            if envelope is None:
                duplicates += 1
                continue
            if self.database is not None:
                payload = envelope.to_dict()
                try:
                    self.database.put_json(self.memory_namespace, article.article_id, payload, expected_version=0)
                except VersionConflict:
                    existing = self.database.get_json(self.memory_namespace, article.article_id)
                    if existing is None or existing["value"] != payload:
                        raise RuntimeError(f"news article evidence conflict: {article.article_id}")
                    duplicates += 1
                    continue
            self._memory.append(envelope)
            accepted += 1
            if envelope.urgency == "critical":
                critical += 1
            elif envelope.urgency == "high":
                high += 1
        return HubIngestResult(
            accepted=accepted,
            duplicates=duplicates,
            memory_size=len(self._memory),
            critical_count=critical,
            high_count=high,
        )

    def event(self, event_type: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        created_at_ms = int(time.time() * 1000)
        event = {
            "event_id": f"news_event_{uuid.uuid4().hex}",
            "created_at_ms": created_at_ms,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(created_at_ms / 1000)),
            "type": str(event_type),
            "message": str(message),
            "level": str(level),
            "data": data or {},
        }
        if self.database is not None:
            self.database.put_json(self.event_namespace, event["event_id"], event, expected_version=0)
        self._events.append(event)

    def memory(self, limit: int = 100) -> list[dict[str, Any]]:
        return [item.to_dict() for item in list(self._memory)[-max(1, min(int(limit), 1000)) :]][::-1]

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self._events)[-max(1, min(int(limit), 1000)) :][::-1]

    def latest(self) -> dict[str, Any] | None:
        return self._memory[-1].to_dict() if self._memory else None

    def state(self) -> dict[str, Any]:
        impacts = Counter(item.impact for item in self._memory)
        urgencies = Counter(item.urgency for item in self._memory)
        article_total = len(list_json_items(self.database, self.memory_namespace)) if self.database is not None else len(self._memory)
        event_total = len(list_json_items(self.database, self.event_namespace)) if self.database is not None else len(self._events)
        return {
            "memory_size": len(self._memory),
            "event_size": len(self._events),
            "article_history_count": article_total,
            "event_history_count": event_total,
            "database_backed": self.database is not None,
            "impact_counts": dict(impacts),
            "urgency_counts": dict(urgencies),
            "latest": self.latest(),
        }

    def _restore(self) -> None:
        if self.database is None:
            return
        memory_rows = list_json_items(self.database, self.memory_namespace, limit=self._memory.maxlen, newest_first=True)
        event_rows = list_json_items(self.database, self.event_namespace, limit=self._events.maxlen, newest_first=True)
        for row in reversed(memory_rows):
            self._memory.append(_envelope_from_dict(row["value"]))
        for row in reversed(event_rows):
            value = row["value"]
            if not isinstance(value, dict):
                raise RuntimeError("persisted news event must be an object")
            self._events.append(dict(value))


def _envelope_from_dict(value: Any) -> NewsEnvelope:
    if not isinstance(value, dict):
        raise RuntimeError("persisted news envelope must be an object")
    article_raw = value.get("article")
    fetched_raw = value.get("fetched")
    if not isinstance(article_raw, dict) or not isinstance(fetched_raw, dict):
        raise RuntimeError("persisted news envelope is incomplete")
    article = NewsArticle(
        article_id=str(article_raw.get("article_id", "")),
        title=str(article_raw.get("title", "")),
        source=str(article_raw.get("source", "")),
        category=str(article_raw.get("category", "")),
        published_at=str(article_raw.get("published_at", "")),
        link=str(article_raw.get("link", "")),
        summary=str(article_raw.get("summary", "")),
        language=str(article_raw.get("language", "")),
        source_type=str(article_raw.get("source_type", "")),
    )
    fetched = SourceFetch(
        source_id=str(fetched_raw.get("source_id", "")),
        source_name=str(fetched_raw.get("source_name", "")),
        source_type=str(fetched_raw.get("source_type", "")),
        category=str(fetched_raw.get("category", "")),
        requested_at_ms=_positive_int(fetched_raw.get("requested_at_ms"), "requested_at_ms"),
        received_at_ms=_positive_int(fetched_raw.get("received_at_ms"), "received_at_ms"),
        status_code=int(fetched_raw.get("status_code", 0)),
        verified=bool(fetched_raw.get("verified")),
        error=str(fetched_raw.get("error", "")),
        item_count=max(int(fetched_raw.get("item_count", 0)), 0),
    )
    return NewsEnvelope(
        agent_id=str(value.get("agent_id", "")),
        agent_name=str(value.get("agent_name", "")),
        category=str(value.get("category", "")),
        article=article,
        fetched=fetched,
        sentiment=_finite(value.get("sentiment"), "sentiment"),
        relevance=_finite(value.get("relevance"), "relevance"),
        reliability=_finite(value.get("reliability"), "reliability"),
        urgency=str(value.get("urgency", "")),
        impact=str(value.get("impact", "")),
        score=_finite(value.get("score"), "score"),
        reasons=tuple(str(item) for item in (value.get("reasons") or [])),
        detected_at=str(value.get("detected_at", "")),
    )


def _finite(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RuntimeError(f"persisted {name} must be finite")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise RuntimeError(f"persisted {name} must be positive")
    return parsed


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
