"""Real-source collector for the canonical News Intelligence network.

Only enabled RSS/Atom sources are collected here.  Unsupported social or HTML
sources stay visible in ``news_monitor`` but are never silently converted into
synthetic articles.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

import feedparser
import httpx

from news_monitor.sources import default_sources

from .models import NewsArticle, SourceFetch


_DEFAULT_SOURCE_IDS = (
    "coinbase_blog",
    "kraken_blog",
    "cointelegraph_rss",
    "coindesk_rss",
    "reuters_markets",
    "cnbc_finance",
    "federal_reserve",
    "sec_press",
    "treasury_press",
    "ecb_press",
    "cisa_alerts",
    "bbc_world",
)


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    url: str
    category: str
    source_type: str = "rss"
    language: str = "en"
    trust_score: int = 60
    note: str = ""


class SourceCollector:
    """Fetch and normalize RSS/Atom articles with explicit failure evidence."""

    def __init__(
        self,
        definitions: Iterable[SourceDefinition] | None = None,
        *,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.definitions = list(definitions or [])
        configured_timeout = timeout_seconds if timeout_seconds is not None else _float_env("NEWS_AGENT_HTTP_TIMEOUT_SECONDS", 8.0)
        self.timeout_seconds = min(max(float(configured_timeout), 1.0), 20.0)
        self._client = client

    def collect(self, definition: SourceDefinition) -> tuple[list[NewsArticle], SourceFetch]:
        requested_at_ms = int(time.time() * 1000)
        status_code = 0
        error = ""
        articles: list[NewsArticle] = []
        try:
            response = self._get(definition.url)
            status_code = int(response.status_code)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            bozo_error = getattr(parsed, "bozo_exception", None)
            entries = list(getattr(parsed, "entries", []) or [])
            if bozo_error and not entries:
                raise ValueError(f"invalid feed: {bozo_error}")
            max_items = _bounded_int("NEWS_AGENT_ITEMS_PER_SOURCE", default=25, minimum=1, maximum=100)
            articles = [
                _article(definition, entry)
                for entry in entries[:max_items]
                if _entry_title(entry)
            ]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            articles = []
        received_at_ms = max(int(time.time() * 1000), requested_at_ms + 1)
        fetched = SourceFetch(
            source_id=definition.source_id,
            source_name=definition.name,
            source_type=definition.source_type,
            category=definition.category,
            requested_at_ms=requested_at_ms,
            received_at_ms=received_at_ms,
            status_code=status_code,
            verified=not bool(error) and status_code == 200,
            error=error,
            item_count=len(articles),
        )
        return articles, fetched

    def _get(self, url: str) -> httpx.Response:
        headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*", "User-Agent": "SharipovAI-NewsIntelligence/1.0"}
        if self._client is not None:
            return self._client.get(url, timeout=self.timeout_seconds, headers=headers, follow_redirects=True)
        return httpx.get(url, timeout=self.timeout_seconds, headers=headers, follow_redirects=True)


def source_definitions() -> list[SourceDefinition]:
    """Build the active real-feed allowlist from the shared source registry."""

    configured = tuple(
        item.strip()
        for item in os.getenv("NEWS_AGENT_SOURCE_IDS", ",".join(_DEFAULT_SOURCE_IDS)).split(",")
        if item.strip()
    )
    wanted = set(configured)
    definitions: list[SourceDefinition] = []
    for source in default_sources():
        if source.id not in wanted:
            continue
        if not source.enabled or source.requires_credentials or source.kind != "rss":
            continue
        definitions.append(
            SourceDefinition(
                source_id=source.id,
                name=source.name,
                url=source.url,
                category=source.category,
                source_type=source.kind,
                trust_score=int(source.trust_score),
                note=source.note,
            )
        )
    return definitions


def _article(definition: SourceDefinition, entry: Any) -> NewsArticle:
    title = _entry_title(entry)
    link = str(_entry_value(entry, "link", "")).strip()
    summary = str(_entry_value(entry, "summary", _entry_value(entry, "description", ""))).strip()
    published = str(_entry_value(entry, "published", _entry_value(entry, "updated", ""))).strip()
    if not published:
        published = datetime.now(UTC).replace(microsecond=0).isoformat()
    identity = "|".join((definition.source_id, link, title, published))
    article_id = hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()
    return NewsArticle(
        article_id=article_id,
        title=title,
        source=definition.name,
        category=definition.category,
        published_at=published,
        link=link,
        summary=summary,
        language=definition.language,
        source_type=definition.source_type,
    )


def _entry_title(entry: Any) -> str:
    return str(_entry_value(entry, "title", "")).strip()


def _entry_value(entry: Any, key: str, default: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


__all__ = ["SourceCollector", "SourceDefinition", "source_definitions"]
