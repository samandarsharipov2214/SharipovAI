"""Real RSS reader for Social News Monitor.

The reader performs explicit HTTP requests with a browser-like User-Agent,
timeouts and redirects before handing response bytes to feedparser. This avoids
silent empty feeds/403 responses that happened when feedparser fetched URLs
directly on Render.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import os
from typing import Any

import feedparser
import httpx

from .sources import default_sources

USER_AGENT = os.getenv(
    "NEWS_HTTP_USER_AGENT",
    "SharipovAI-NewsMonitor/1.0 (+https://github.com/samandarsharipov2214/SharipovAI)",
)
DEFAULT_TIMEOUT_SECONDS = max(3.0, float(os.getenv("NEWS_HTTP_TIMEOUT_SECONDS", "10") or 10))
DEFAULT_WORKERS = max(1, min(int(os.getenv("NEWS_RSS_WORKERS", "8") or 8), 16))


def rss_status() -> dict[str, object]:
    """Return configured RSS source status."""

    sources = [source for source in default_sources() if source.kind == "rss" and source.enabled]
    return {
        "enabled": True,
        "source_count": len(sources),
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        "workers": DEFAULT_WORKERS,
        "user_agent_configured": bool(USER_AGENT),
        "sources": [source.to_dict() for source in sources],
        "message": "RSS reader включён. HTTP fetch использует timeout, redirect и User-Agent.",
    }


def read_rss_items(limit_per_source: int = 8) -> dict[str, object]:
    """Read latest items from allowlisted RSS sources with diagnostics."""

    limit = max(int(limit_per_source), 1)
    sources = [source for source in default_sources() if source.kind == "rss" and source.enabled]
    items: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    source_results: list[dict[str, object]] = []

    with ThreadPoolExecutor(max_workers=min(DEFAULT_WORKERS, max(len(sources), 1))) as pool:
        future_map = {pool.submit(_read_one_source, source, limit): source for source in sources}
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive isolation
                result = {
                    "source_id": source.id,
                    "source_name": source.name,
                    "status": "error",
                    "item_count": 0,
                    "items": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            source_results.append({key: value for key, value in result.items() if key != "items"})
            items.extend(result.get("items", []))
            if result.get("error"):
                errors.append({
                    "source_id": str(result.get("source_id", source.id)),
                    "source_name": str(result.get("source_name", source.name)),
                    "error": str(result.get("error")),
                    "http_status": str(result.get("http_status", "")),
                })

    source_results.sort(key=lambda item: str(item.get("source_id", "")))
    working_sources = sum(1 for result in source_results if int(result.get("item_count", 0) or 0) > 0)
    return {
        "status": "ok" if items else "empty",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "rss": rss_status(),
        "items": items,
        "errors": errors,
        "diagnostics": {
            "source_count": len(sources),
            "working_sources": working_sources,
            "failed_or_empty_sources": len(sources) - working_sources,
            "item_count": len(items),
            "source_results": source_results,
        },
    }


def _read_one_source(source: Any, limit: int) -> dict[str, object]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.8",
    }
    try:
        with httpx.Client(
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = client.get(source.url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return {
            "source_id": source.id,
            "source_name": source.name,
            "status": "http_error",
            "http_status": exc.response.status_code,
            "item_count": 0,
            "items": [],
            "error": f"HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        return {
            "source_id": source.id,
            "source_name": source.name,
            "status": "network_error",
            "item_count": 0,
            "items": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    feed = feedparser.parse(response.content)
    entries = list(getattr(feed, "entries", []) or [])
    if not entries:
        parse_error = getattr(feed, "bozo_exception", None)
        return {
            "source_id": source.id,
            "source_name": source.name,
            "status": "parse_empty",
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "item_count": 0,
            "items": [],
            "error": f"RSS parse empty: {parse_error}" if parse_error else "RSS/Atom feed contains no entries",
        }

    normalized: list[dict[str, object]] = []
    for entry in entries[:limit]:
        title = str(entry.get("title", "") or "Untitled RSS item")
        normalized.append(
            {
                "source_id": source.id,
                "source_name": source.name,
                "kind": "rss",
                "title": title,
                "summary": _entry_text(entry),
                "url": str(entry.get("link", source.url) or source.url),
                "published_at": _published_iso(entry),
                "trust_score": source.trust_score,
            }
        )
    return {
        "source_id": source.id,
        "source_name": source.name,
        "status": "ok",
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "bytes": len(response.content),
        "item_count": len(normalized),
        "items": normalized,
        "error": "",
    }


def _entry_text(entry: Any) -> str:
    summary = entry.get("summary", "") or entry.get("description", "") or ""
    return summary[:900] if isinstance(summary, str) else str(summary)[:900]


def _published_iso(entry: Any) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=UTC).isoformat()
        except Exception:
            pass
    return datetime.now(tz=UTC).isoformat()
