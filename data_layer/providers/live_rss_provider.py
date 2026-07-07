"""Live RSS data provider using feedparser.

The provider downloads and parses RSS feeds through ``feedparser``. Individual
bad feeds or malformed entries are skipped so one failure does not prevent
successful feeds from returning data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import struct_time
from typing import Any

from data_layer.models import DataBatch, DataItem

from .base import BaseDataProvider


class LiveRSSProvider(BaseDataProvider):
    """RSS provider backed by feedparser."""

    PROVIDER_NAME: str = "LiveRSSProvider"

    def __init__(self, feed_urls: list[str]) -> None:
        """Initialize the provider.

        Args:
            feed_urls: RSS feed URLs to parse.
        """

        self._feed_urls = list(feed_urls)

    def name(self) -> str:
        """Return the provider name."""

        return self.PROVIDER_NAME

    def fetch(self) -> DataBatch:
        """Fetch and parse configured RSS feeds.

        Returns:
            Data batch containing all successfully parsed feed entries.
        """

        items: list[DataItem] = []

        for feed_url in self._feed_urls:
            try:
                parsed_feed = _parse_feed(feed_url)
            except Exception:
                continue

            if bool(_get_value(parsed_feed, "bozo", False)) and not _entries(parsed_feed):
                continue

            source = _source_name(parsed_feed, feed_url)
            for entry in _entries(parsed_feed):
                item = _entry_to_data_item(entry=entry, source=source, feed_url=feed_url)
                if item is not None:
                    items.append(item)

        return DataBatch(items=items)


def _entry_to_data_item(entry: Any, source: str, feed_url: str) -> DataItem | None:
    """Convert a feedparser entry into a data item.

    Args:
        entry: feedparser entry object.
        source: Resolved feed source name.
        feed_url: Source feed URL.

    Returns:
        Data item or ``None`` when the entry is unusable.
    """

    title = str(_get_value(entry, "title", "")).strip()
    content = _entry_content(entry).strip()
    if not title and not content:
        return None

    return DataItem(
        source=source,
        category="rss",
        title=title,
        content=content,
        url=_optional_string(_get_value(entry, "link", None)),
        published_at=_published_at(entry),
        metadata={
            "feed_url": feed_url,
            "id": _optional_string(_get_value(entry, "id", None)),
            "author": _optional_string(_get_value(entry, "author", None)),
            "tags": _tags(entry),
        },
    )


def _parse_feed(feed_url: str) -> Any:
    """Parse a feed URL using feedparser.

    Args:
        feed_url: RSS feed URL.

    Returns:
        Parsed feed object.
    """

    import feedparser

    return feedparser.parse(feed_url)


def _entry_content(entry: Any) -> str:
    """Extract content text from a feed entry."""

    summary = _get_value(entry, "summary", None)
    if summary is not None:
        return str(summary)

    content = _get_value(entry, "content", None)
    if isinstance(content, list) and content:
        first_content = content[0]
        return str(_get_value(first_content, "value", ""))

    return ""


def _published_at(entry: Any) -> datetime | None:
    """Extract a timezone-aware publication timestamp from a feed entry."""

    parsed = _get_value(entry, "published_parsed", None)
    if parsed is None:
        parsed = _get_value(entry, "updated_parsed", None)

    if not isinstance(parsed, struct_time):
        return None

    return datetime(*parsed[:6], tzinfo=timezone.utc)


def _source_name(parsed_feed: Any, feed_url: str) -> str:
    """Resolve source name from feed metadata."""

    feed = _get_value(parsed_feed, "feed", {})
    title = _get_value(feed, "title", None)
    if title:
        return str(title)
    return feed_url


def _entries(parsed_feed: Any) -> list[Any]:
    """Return feed entries as a list."""

    entries = _get_value(parsed_feed, "entries", [])
    if isinstance(entries, list):
        return entries
    return []


def _tags(entry: Any) -> list[str]:
    """Extract feed entry tags."""

    tags = _get_value(entry, "tags", [])
    if not isinstance(tags, list):
        return []

    values: list[str] = []
    for tag in tags:
        term = _get_value(tag, "term", None)
        if term:
            values.append(str(term))
    return values


def _optional_string(value: Any) -> str | None:
    """Convert a value to an optional string."""

    if value is None:
        return None
    return str(value)


def _get_value(source: Any, key: str, default: Any) -> Any:
    """Read a value from dict-like or attribute-like objects."""

    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)
