"""Adapters from the existing real-news monitor into canonical News Intelligence."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from news_monitor.sources import default_sources
from news_monitor.storage import load_news_state

from .models import NewsArticle, SourceFetch

_BLOCKED_MODES = ("demo", "synthetic", "mock", "fixture", "sample")


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: str
    category: str
    url: str
    trust_score: int
    enabled: bool = True
    requires_credentials: bool = False

    def __post_init__(self) -> None:
        if not self.source_id or not self.name or not self.source_type or not self.category:
            raise ValueError("source definition fields cannot be empty")
        if not 0 <= int(self.trust_score) <= 100:
            raise ValueError("trust_score must be between 0 and 100")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "category": self.category,
            "url": self.url,
            "trust_score": int(self.trust_score),
            "enabled": bool(self.enabled),
            "requires_credentials": bool(self.requires_credentials),
        }


@lru_cache(maxsize=1)
def _definitions() -> tuple[SourceDefinition, ...]:
    return tuple(
        SourceDefinition(
            source_id=source.id,
            name=source.name,
            source_type=source.kind,
            category=source.category,
            url=source.url,
            trust_score=source.trust_score,
            enabled=source.enabled,
            requires_credentials=source.requires_credentials,
        )
        for source in default_sources()
        if source.enabled
    )


def source_definitions() -> list[SourceDefinition]:
    return list(_definitions())


class SourceCollector:
    """Read only already-fetched real items; never manufacture a live article."""

    def __init__(self, definitions: Iterable[SourceDefinition] | None = None) -> None:
        values = tuple(definitions or source_definitions())
        self._definitions = {item.source_id: item for item in values}
        self._cached_at_ms = 0
        self._cached_state: dict[str, Any] | None = None

    def collect(self, definition: SourceDefinition) -> tuple[list[NewsArticle], SourceFetch]:
        if definition.source_id not in self._definitions:
            raise KeyError(f"Source is not registered: {definition.source_id}")

        requested_at_ms = int(time.time() * 1000)
        error = ""
        try:
            state = self._state(requested_at_ms)
        except Exception as exc:
            state = {}
            error = f"{type(exc).__name__}: {exc}"

        mode = str(state.get("source_mode", "")).strip().lower()
        news = state.get("news") if isinstance(state.get("news"), dict) else {}
        if not mode:
            mode = str(news.get("source_mode", "")).strip().lower()
        if any(marker in mode for marker in _BLOCKED_MODES):
            error = f"untrusted source mode blocked: {mode}"
            raw_items: list[Any] = []
        else:
            candidate_items = news.get("items", [])
            raw_items = candidate_items if isinstance(candidate_items, list) else []

        articles: list[NewsArticle] = []
        seen: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("source_id", "")).strip() != definition.source_id:
                continue
            if any(bool(raw.get(flag)) for flag in ("synthetic", "demo", "mock", "fixture")):
                continue
            try:
                item = _article_from_item(definition, raw)
            except (TypeError, ValueError):
                continue
            if item.article_id in seen:
                continue
            seen.add(item.article_id)
            articles.append(item)

        source_errors = state.get("last_refresh_errors", [])
        if not error and isinstance(source_errors, list):
            for value in source_errors:
                text = str(value)
                if definition.source_id in text:
                    error = text
                    break

        received_at_ms = max(int(time.time() * 1000), requested_at_ms)
        trusted_mode = not any(marker in mode for marker in _BLOCKED_MODES)
        fetched = SourceFetch(
            source_id=definition.source_id,
            source_name=definition.name,
            source_type=definition.source_type,
            category=definition.category,
            requested_at_ms=requested_at_ms,
            received_at_ms=received_at_ms,
            status_code=0 if error else 200,
            verified=bool(trusted_mode and not error),
            error=error,
            item_count=len(articles),
        )
        return articles, fetched

    def _state(self, now_ms: int) -> dict[str, Any]:
        if self._cached_state is None or now_ms - self._cached_at_ms >= 1_000:
            value = load_news_state()
            if not isinstance(value, dict):
                raise RuntimeError("news state must be an object")
            self._cached_state = value
            self._cached_at_ms = now_ms
        return self._cached_state


def _article_from_item(definition: SourceDefinition, raw: dict[str, Any]) -> NewsArticle:
    title = str(raw.get("title", "")).strip()
    published_at = str(raw.get("published_at", "")).strip()
    link = str(raw.get("url") or raw.get("link") or "").strip()
    if not title or not published_at:
        raise ValueError("real news item lacks title or timestamp")
    article_id = str(raw.get("article_id", "")).strip() or _article_id(
        definition.source_id,
        link,
        title,
        published_at,
    )
    symbols = tuple(str(value) for value in (raw.get("symbols") or []) if str(value).strip())
    tags = tuple(str(value) for value in (raw.get("tags") or []) if str(value).strip())
    credibility_raw = raw.get("credibility_percent")
    credibility = float(credibility_raw) if credibility_raw not in (None, "") else float(definition.trust_score)
    return NewsArticle(
        article_id=article_id,
        title=title,
        source=str(raw.get("source_name") or definition.name),
        category=str(raw.get("category") or definition.category),
        published_at=published_at,
        link=link,
        summary=str(raw.get("summary", "")),
        language=str(raw.get("language") or "und"),
        source_type=str(raw.get("kind") or raw.get("source_type") or definition.source_type),
        credibility_percent=max(0.0, min(credibility, 100.0)),
        urgency=str(raw.get("urgency", "")),
        impact=str(raw.get("impact", "")),
        impact_score=float(raw.get("impact_score", 0.0) or 0.0),
        reason=str(raw.get("reason", "")),
        symbols=symbols,
        tags=tags,
    )


def _article_id(source_id: str, link: str, title: str, published_at: str) -> str:
    raw = "\n".join((source_id, link, title, published_at)).encode("utf-8")
    return f"news_{hashlib.sha256(raw).hexdigest()}"


__all__ = ["SourceCollector", "SourceDefinition", "source_definitions"]
