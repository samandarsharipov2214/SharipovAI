"""Real RSS reader for Social News Monitor.

This reader is read-only and safe by default. It fetches enabled RSS sources from
our source allowlist, normalizes items, and lets analyzer.py decide trust/impact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import feedparser

from .sources import default_sources


def rss_status() -> dict[str, object]:
    """Return configured RSS source status."""

    sources = [source for source in default_sources() if source.kind == "rss" and source.enabled]
    return {
        "enabled": True,
        "source_count": len(sources),
        "sources": [source.to_dict() for source in sources],
        "message": "RSS reader включён. Читает только allowlist RSS источники.",
    }


def read_rss_items(limit_per_source: int = 8) -> dict[str, object]:
    """Read latest items from allowlisted RSS sources."""

    items: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    sources = [source for source in default_sources() if source.kind == "rss" and source.enabled]
    for source in sources:
        try:
            feed = feedparser.parse(source.url)
        except Exception as exc:
            errors.append({"source_id": source.id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if getattr(feed, "bozo", False) and not getattr(feed, "entries", None):
            errors.append({"source_id": source.id, "error": "RSS parse failed"})
            continue
        for entry in list(getattr(feed, "entries", []))[: max(int(limit_per_source), 1)]:
            title = str(getattr(entry, "title", "") or "Untitled RSS item")
            summary = _entry_text(entry)
            items.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "kind": "rss",
                    "title": title,
                    "summary": summary,
                    "url": str(getattr(entry, "link", source.url) or source.url),
                    "published_at": _published_iso(entry),
                    "trust_score": source.trust_score,
                }
            )
    return {
        "status": "ok" if items else "empty",
        "rss": rss_status(),
        "items": items,
        "errors": errors,
    }


def _entry_text(entry: Any) -> str:
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if isinstance(summary, str):
        return summary[:900]
    return str(summary)[:900]


def _published_iso(entry: Any) -> str:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=UTC).isoformat()
        except Exception:
            pass
    return datetime.now(tz=UTC).isoformat()
