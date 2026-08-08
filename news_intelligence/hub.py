"""Central memory, events and summaries for the existing News Intelligence network.

ProjectDatabase is the source of truth. RAM deques remain bounded read caches so
restarts no longer erase article evidence or AI events. Immutable article
identity is stored separately from append-only source fetch observations so a
later fetch timestamp can never masquerade as an article evidence conflict.
"""
from __future__ import annotations

import math
import os
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Mapping

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
        # ``news_memory`` is retained as a backward-compatible analyzed-envelope
        # store. New immutable identity checks use ``news_article_evidence``;
        # every source retrieval is written separately to project_events.
        self.memory_namespace = "news_memory"
        self.article_namespace = "news_article_evidence"
        self.fetch_observation_namespace = "news_fetch_observations"
        self.event_namespace = "news_events"
        self._restore()

    def ingest(self, agent: SourceAgent, articles: list[NewsArticle], fetched: SourceFetch) -> HubIngestResult:
        accepted = 0
        duplicates = 0
        critical = 0
        high = 0
        for article in articles:
            if self.database is not None:
                self._persist_article_evidence(article)
                self._record_fetch_observation(agent, article, fetched)

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
                    if existing is None or not _same_article_evidence(existing.get("value"), payload):
                        return  # skip duplicate article
                    # The legacy envelope contains one historical fetch snapshot.
                    # A later fetch is now preserved independently as an
                    # observation and therefore does not rewrite the envelope.
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

    def fetch_observations(self, *, article_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return append-only fetch evidence without mutating article identity."""
        if self.database is None:
            return []
        return self.database.list_events(
            self.fetch_observation_namespace,
            entity_type="source_fetch",
            entity_id=article_id,
            limit=max(1, min(int(limit), 1000)),
        )

    def latest(self) -> dict[str, Any] | None:
        return self._memory[-1].to_dict() if self._memory else None

    def state(self) -> dict[str, Any]:
        impacts = Counter(item.impact for item in self._memory)
        urgencies = Counter(item.urgency for item in self._memory)
        article_total = len(list_json_items(self.database, self.memory_namespace)) if self.database is not None else len(self._memory)
        immutable_article_total = len(list_json_items(self.database, self.article_namespace)) if self.database is not None else 0
        event_total = len(list_json_items(self.database, self.event_namespace)) if self.database is not None else len(self._events)
        return {
            "memory_size": len(self._memory),
            "event_size": len(self._events),
            "article_history_count": article_total,
            "immutable_article_evidence_count": immutable_article_total,
            "fetch_observation_storage": "project_events" if self.database is not None else "unavailable",
            "article_fetch_evidence_separated": self.database is not None,
            "event_history_count": event_total,
            "database_backed": self.database is not None,
            "impact_counts": dict(impacts),
            "urgency_counts": dict(urgencies),
            "latest": self.latest(),
        }

    def _persist_article_evidence(self, article: NewsArticle) -> None:
        if self.database is None:
            return
        payload = article.to_dict()
        existing = self.database.get_json(self.article_namespace, article.article_id)
        if existing is None:
            try:
                self.database.put_json(self.article_namespace, article.article_id, payload, expected_version=0)
                return
            except VersionConflict:
                existing = self.database.get_json(self.article_namespace, article.article_id)
        if existing is None or not _same_article_evidence(existing.get("value"), payload):
            raise RuntimeError(f"news article evidence conflict: {article.article_id}")

    def _record_fetch_observation(self, agent: SourceAgent, article: NewsArticle, fetched: SourceFetch) -> None:
        if self.database is None:
            return
        payload = {
            "article_id": article.article_id,
            "agent_id": agent.definition.source_id,
            "source_id": fetched.source_id,
            "fetch": fetched.to_dict(),
            "observed_at_ms": int(fetched.received_at_ms),
            "article_evidence_namespace": self.article_namespace,
        }
        self.database.append_event(
            self.fetch_observation_namespace,
            "source_fetch",
            article.article_id,
            payload,
            created_at_ms=max(int(fetched.received_at_ms), 1),
        )

    def _restore(self) -> None:
        if self.database is None:
            return
        memory_rows = list_json_items(self.database, self.memory_namespace, limit=self._memory.maxlen, newest_first=True)
        event_rows = list_json_items(self.database, self.event_namespace, limit=self._events.maxlen, newest_first=True)
        for row in reversed(memory_rows):
            value = row["value"]
            envelope = _envelope_from_dict(value)
            # Backward-compatible migration: old ``news_memory`` rows remain
            # readable, while immutable article identity is copied once into the
            # dedicated namespace. Existing data is never deleted or rewritten.
            self._persist_article_evidence(envelope.article)
            self._memory.append(envelope)
        for row in reversed(event_rows):
            value = row["value"]
            if not isinstance(value, dict):
                raise RuntimeError("persisted news event must be an object")
            self._events.append(dict(value))


def _same_article_evidence(existing: Any, candidate: Any) -> bool:
    if not isinstance(existing, Mapping) or not isinstance(candidate, Mapping):
        return False
    existing_article = existing.get("article") if isinstance(existing.get("article"), Mapping) else existing
    candidate_article = candidate.get("article") if isinstance(candidate.get("article"), Mapping) else candidate
    if not isinstance(existing_article, Mapping) or not isinstance(candidate_article, Mapping):
        return False
    immutable_fields = (
        "article_id",
        "title",
        "source",
        "category",
        "published_at",
        "link",
        "summary",
        "language",
        "source_type",
    )
    return all(str(existing_article.get(field, "")) == str(candidate_article.get(field, "")) for field in immutable_fields)


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
        status_code=_integer(fetched_raw.get("status_code", 0), "status_code"),
        verified=bool(fetched_raw.get("verified")),
        error=str(fetched_raw.get("error", "")),
        item_count=max(_integer(fetched_raw.get("item_count", 0), "item_count"), 0),
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
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"persisted {name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise RuntimeError(f"persisted {name} must be finite")
    return parsed


def _integer(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"persisted {name} must be an integer") from exc


def _positive_int(value: Any, name: str) -> int:
    parsed = _integer(value, name)
    if parsed <= 0:
        raise RuntimeError(f"persisted {name} must be positive")
    return parsed


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
