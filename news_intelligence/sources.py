"""Verified read-only source definitions for the existing News Intelligence organ."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import feedparser
import httpx

from .models import NewsArticle, SourceFetch


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: str
    category: str
    url: str
    language: str = "en"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if not self.source_id.strip() or not self.name.strip():
            raise ValueError("source identity is required")
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("news source URL must be an absolute HTTPS URL")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "category": self.category,
            "url": self.url,
            "language": self.language,
        }


def source_definitions() -> tuple[SourceDefinition, ...]:
    """Return bounded official sources; no demo or synthetic articles are included."""

    return (
        SourceDefinition(
            source_id="sec_press_releases",
            name="U.S. Securities and Exchange Commission",
            source_type="official_rss",
            category="regulation_official",
            url="https://www.sec.gov/news/pressreleases.rss",
        ),
        SourceDefinition(
            source_id="federal_reserve_press",
            name="Federal Reserve",
            source_type="official_rss",
            category="macro_official",
            url="https://www.federalreserve.gov/feeds/press_all.xml",
        ),
    )


class SourceCollector:
    """Small fail-closed RSS collector used only by the canonical News organ."""

    def __init__(self, definitions: tuple[SourceDefinition, ...] | list[SourceDefinition]) -> None:
        self.definitions = tuple(definitions)

    def collect(self, definition: SourceDefinition) -> tuple[list[NewsArticle], SourceFetch]:
        requested_at_ms = int(time.time() * 1000)
        articles: list[NewsArticle] = []
        status_code = 0
        error = ""
        verified = False
        try:
            response = httpx.get(
                definition.url,
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "SharipovAI/1.0 read-only-news-monitor"},
            )
            status_code = int(response.status_code)
            response.raise_for_status()
            parsed = feedparser.loads(response.content)
            if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", None):
                raise RuntimeError(str(getattr(parsed, "bozo_exception", "invalid RSS payload")))
            for entry in list(getattr(parsed, "entries", []))[:20]:
                title = str(entry.get("title", "")).strip()
                link = str(entry.get("link", "")).strip()
                published = str(entry.get("published", entry.get("updated", ""))).strip()
                summary = str(entry.get("summary", entry.get("description", ""))).strip()
                if not title or not link or urlsplit(link).scheme not in {"http", "https"}:
                    continue
                article_id = hashlib.sha256(
                    f"{definition.source_id}|{link}|{title}|{published}".encode("utf-8")
                ).hexdigest()
                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        title=title,
                        source=definition.name,
                        category=definition.category,
                        published_at=published or "unknown",
                        link=link,
                        summary=summary,
                        language=definition.language,
                        source_type=definition.source_type,
                    )
                )
            verified = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        received_at_ms = max(int(time.time() * 1000), requested_at_ms)
        fetched = SourceFetch(
            source_id=definition.source_id,
            source_name=definition.name,
            source_type=definition.source_type,
            category=definition.category,
            requested_at_ms=requested_at_ms,
            received_at_ms=received_at_ms,
            status_code=status_code,
            verified=verified,
            error=error,
            item_count=len(articles),
        )
        return articles, fetched


__all__ = ["SourceCollector", "SourceDefinition", "source_definitions"]
