"""Verified source definitions and collectors for News Intelligence.

Only responses received from configured sources become articles. Network errors
produce explicit SourceFetch evidence and never generate fallback headlines.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from .models import NewsArticle, SourceFetch

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    url: str
    source_type: str
    category: str
    language: str = "en"
    reliability: float = 0.80
    verified: bool = True

    def __post_init__(self) -> None:
        for name in ("source_id", "name", "url", "source_type", "category", "language"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        reliability = float(self.reliability)
        if not 0.0 <= reliability <= 1.0:
            raise ValueError("reliability must be between 0 and 1")
        object.__setattr__(self, "reliability", reliability)
        object.__setattr__(self, "verified", bool(self.verified))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "url": self.url,
            "source_type": self.source_type,
            "category": self.category,
            "language": self.language,
            "reliability": self.reliability,
            "verified": self.verified,
        }


def source_definitions() -> list[SourceDefinition]:
    """Return the stable canonical source registry without hidden fallbacks."""
    return [
        SourceDefinition("coindesk", "CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "rss", "crypto", "en", 0.84),
        SourceDefinition("cointelegraph", "Cointelegraph", "https://cointelegraph.com/rss", "rss", "crypto", "en", 0.76),
        SourceDefinition("bbc_world", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "rss", "world", "en", 0.88),
        SourceDefinition("bbc_business", "BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "rss", "finance", "en", 0.88),
        SourceDefinition("federal_reserve", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "official_rss", "finance", "en", 0.98),
        SourceDefinition("sec_press", "U.S. SEC Press Releases", "https://www.sec.gov/news/pressreleases.rss", "official_rss", "regulation", "en", 0.98),
        SourceDefinition("ecb_press", "European Central Bank", "https://www.ecb.europa.eu/rss/press.html", "official_rss", "finance", "en", 0.98),
        SourceDefinition("un_news", "United Nations News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml", "official_rss", "world", "en", 0.96),
        SourceDefinition("nato_news", "NATO News", "https://www.nato.int/cps/en/natohq/news_rss.htm", "official_rss", "security", "en", 0.96),
        SourceDefinition("noaa_alerts", "NOAA Weather Alerts", "https://www.weather.gov/rss_page.php?site_name=nws", "official_rss", "weather", "en", 0.94),
        SourceDefinition("white_house", "White House Briefing Room", "https://www.whitehouse.gov/briefing-room/feed/", "official_rss", "politics", "en", 0.97),
        SourceDefinition("who_news", "World Health Organization", "https://www.who.int/rss-feeds/news-english.xml", "official_rss", "health", "en", 0.97),
    ]


class SourceCollector:
    def __init__(
        self,
        definitions: list[SourceDefinition] | None = None,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.definitions = list(definitions or source_definitions())
        self._by_id = {item.source_id: item for item in self.definitions}
        if len(self._by_id) != len(self.definitions):
            raise ValueError("source identifiers must be unique")
        self.timeout_seconds = _bounded_float("NEWS_SOURCE_TIMEOUT_SECONDS", timeout_seconds or 12.0, 2.0, 60.0)
        self.max_items = int(_bounded_float("NEWS_SOURCE_MAX_ITEMS", 25.0, 1.0, 100.0))
        self.client = client

    def collect(self, definition: SourceDefinition) -> tuple[list[NewsArticle], SourceFetch]:
        if definition.source_id not in self._by_id:
            raise KeyError(f"unknown source definition: {definition.source_id}")
        requested_at_ms = int(time.time() * 1000)
        status_code = 0
        try:
            if self.client is not None:
                response = self.client.get(
                    definition.url,
                    headers={"User-Agent": "SharipovAI-News/1.0", "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
            else:
                with httpx.Client(follow_redirects=True, timeout=self.timeout_seconds) as client:
                    response = client.get(
                        definition.url,
                        headers={"User-Agent": "SharipovAI-News/1.0", "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                    )
            status_code = int(response.status_code)
            response.raise_for_status()
            parsed = feedparser.loads(response.content)
            articles = self._articles(definition, list(parsed.entries)[: self.max_items])
            received_at_ms = max(int(time.time() * 1000), requested_at_ms)
            fetched = SourceFetch(
                source_id=definition.source_id,
                source_name=definition.name,
                source_type=definition.source_type,
                category=definition.category,
                requested_at_ms=requested_at_ms,
                received_at_ms=received_at_ms,
                status_code=status_code,
                verified=bool(definition.verified and 200 <= status_code < 300),
                error="",
                item_count=len(articles),
            )
            return articles, fetched
        except Exception as exc:
            received_at_ms = max(int(time.time() * 1000), requested_at_ms)
            fetched = SourceFetch(
                source_id=definition.source_id,
                source_name=definition.name,
                source_type=definition.source_type,
                category=definition.category,
                requested_at_ms=requested_at_ms,
                received_at_ms=received_at_ms,
                status_code=status_code,
                verified=False,
                error=f"{type(exc).__name__}: {exc}",
                item_count=0,
            )
            return [], fetched

    def collect_by_id(self, source_id: str) -> tuple[list[NewsArticle], SourceFetch]:
        definition = self._by_id.get(str(source_id).strip())
        if definition is None:
            raise KeyError(f"unknown source definition: {source_id}")
        return self.collect(definition)

    def _articles(self, definition: SourceDefinition, entries: list[Any]) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        seen: set[str] = set()
        for entry in entries:
            title = _clean(_entry(entry, "title"))
            link = str(_entry(entry, "link") or "").strip()
            if not title or not link:
                continue
            summary = _clean(_entry(entry, "summary") or _entry(entry, "description"))
            published_at = _published_at(entry)
            raw_id = str(_entry(entry, "id") or _entry(entry, "guid") or link).strip()
            article_id = hashlib.sha256(f"{definition.source_id}\n{raw_id}\n{title}".encode("utf-8")).hexdigest()
            if article_id in seen:
                continue
            seen.add(article_id)
            articles.append(
                NewsArticle(
                    article_id=article_id,
                    title=title,
                    source=definition.name,
                    category=definition.category,
                    published_at=published_at,
                    link=link,
                    summary=summary,
                    language=definition.language,
                    source_type=definition.source_type,
                )
            )
        return articles


def _entry(entry: Any, key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _published_at(entry: Any) -> str:
    for key in ("published", "updated", "created"):
        raw = str(_entry(entry, key) or "").strip()
        if not raw:
            continue
        try:
            value = parsedate_to_datetime(raw)
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).isoformat()
        except Exception:
            continue
    return datetime.now(UTC).isoformat()


def _clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return _SPACES.sub(" ", _TAGS.sub(" ", text)).strip()


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["SourceCollector", "SourceDefinition", "source_definitions"]
