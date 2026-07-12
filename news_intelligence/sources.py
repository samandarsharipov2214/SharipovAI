"""Verified source registry and collectors for News Intelligence.

The collector never fabricates fallback articles. Unsupported or unavailable
sources return an explicit error together with an empty article list.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from .models import NewsArticle, SourceFetch


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: str
    category: str
    url: str
    trust_score: int
    language: str = "en"
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "category": self.category,
            "url": self.url,
            "trust_score": self.trust_score,
            "language": self.language,
            "enabled": self.enabled,
        }


_DEFINITIONS: tuple[SourceDefinition, ...] = (
    SourceDefinition("federal_reserve", "Federal Reserve Press Releases", "rss", "macro_official", "https://www.federalreserve.gov/feeds/press_all.xml", 96),
    SourceDefinition("sec_press", "SEC Press Releases", "rss", "regulation_official", "https://www.sec.gov/news/pressreleases.rss", 96),
    SourceDefinition("ecb_press", "European Central Bank", "rss", "macro_official", "https://www.ecb.europa.eu/rss/press.html", 94),
    SourceDefinition("bis_press", "Bank for International Settlements", "rss", "macro_official", "https://www.bis.org/list/press_releases/index.rss", 92),
    SourceDefinition("coinbase_blog", "Coinbase Blog", "rss", "exchange", "https://www.coinbase.com/blog/rss.xml", 88),
    SourceDefinition("kraken_blog", "Kraken Blog", "rss", "exchange", "https://blog.kraken.com/feed", 86),
    SourceDefinition("coindesk_rss", "CoinDesk", "rss", "crypto_news", "https://www.coindesk.com/arc/outboundfeeds/rss/", 78),
    SourceDefinition("cointelegraph_rss", "Cointelegraph", "rss", "crypto_news", "https://cointelegraph.com/rss", 75),
    SourceDefinition("bbc_world", "BBC World", "rss", "world_news", "https://feeds.bbci.co.uk/news/world/rss.xml", 84),
    SourceDefinition("guardian_world", "The Guardian World", "rss", "world_news", "https://www.theguardian.com/world/rss", 76),
    SourceDefinition("npr_news", "NPR News", "rss", "world_news", "https://feeds.npr.org/1001/rss.xml", 80),
    SourceDefinition("cnbc_finance", "CNBC Finance", "rss", "world_finance", "https://www.cnbc.com/id/100003114/device/rss/rss.html", 76),
)


def source_definitions() -> list[SourceDefinition]:
    return list(_DEFINITIONS)


class SourceCollector:
    def __init__(self, definitions: Iterable[SourceDefinition] | None = None) -> None:
        self.definitions = {item.source_id: item for item in (definitions or _DEFINITIONS)}
        self.timeout_seconds = _bounded_float("NEWS_SOURCE_TIMEOUT_SECONDS", default=12.0, minimum=2.0, maximum=60.0)
        self.max_items = _bounded_int("NEWS_SOURCE_MAX_ITEMS", default=30, minimum=1, maximum=200)
        self.user_agent = os.getenv("NEWS_SOURCE_USER_AGENT", "SharipovAI-NewsIntelligence/1.0")

    def collect(self, definition: SourceDefinition) -> tuple[list[NewsArticle], SourceFetch]:
        requested_at_ms = int(time.time() * 1000)
        articles: list[NewsArticle] = []
        status_code = 0
        error = ""
        verified = False
        if not definition.enabled:
            error = "source_disabled"
        elif definition.source_type != "rss":
            error = f"unsupported_source_type:{definition.source_type}"
        else:
            try:
                request = urllib.request.Request(
                    definition.url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    status_code = int(getattr(response, "status", 200) or 200)
                    payload = response.read(4_000_000)
                if status_code != 200:
                    error = f"http_status:{status_code}"
                else:
                    articles = _parse_feed(payload, definition, limit=self.max_items)
                    verified = True
            except urllib.error.HTTPError as exc:
                status_code = int(exc.code)
                error = f"HTTPError:{exc.code}"
            except Exception as exc:
                error = f"{type(exc).__name__}:{exc}"
        received_at_ms = max(int(time.time() * 1000), requested_at_ms)
        return articles, SourceFetch(
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


def _parse_feed(payload: bytes, definition: SourceDefinition, *, limit: int) -> list[NewsArticle]:
    root = ET.fromstring(payload)
    candidates = list(root.findall(".//item"))
    if not candidates:
        candidates = [node for node in root.iter() if _local_name(node.tag) == "entry"]
    output: list[NewsArticle] = []
    for node in candidates[:limit]:
        title = _child_text(node, "title")
        link = _entry_link(node)
        summary = _child_text(node, "description") or _child_text(node, "summary") or _child_text(node, "content")
        published = _child_text(node, "pubDate") or _child_text(node, "published") or _child_text(node, "updated")
        if not title or not link:
            continue
        article_id = hashlib.sha256(f"{definition.source_id}\0{link}\0{title}".encode("utf-8")).hexdigest()
        output.append(NewsArticle(
            article_id=article_id,
            title=_clean_text(title),
            source=definition.name,
            category=definition.category,
            published_at=published or datetime.now(tz=UTC).isoformat(),
            link=link.strip(),
            summary=_clean_text(summary),
            language=definition.language,
            source_type=definition.source_type,
        ))
    return output


def _entry_link(node: ET.Element) -> str:
    direct = _child_text(node, "link")
    if direct:
        return direct
    for child in node:
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href", "").strip()
            if href:
                return href
    return ""


def _child_text(node: ET.Element, name: str) -> str:
    for child in node.iter():
        if _local_name(child.tag) == name:
            if child.text:
                return child.text.strip()
            href = child.attrib.get("href", "").strip()
            if href:
                return href
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_text(value: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", plain).strip()


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def _bounded_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
