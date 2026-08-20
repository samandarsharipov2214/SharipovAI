"""Canonical, bounded provenance helpers for news ingress.

This module is intentionally pure and side-effect free. It normalizes source
publication timestamps against the local fetch time, validates public news URLs,
and creates a compact stable provenance identifier without storing raw feed
payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from urllib.parse import urlsplit

MAX_FUTURE_SKEW = timedelta(minutes=5)
SAFE_PUBLIC_URL_SCHEMES = frozenset({"http", "https"})


def utc_iso(value: datetime) -> str:
    """Return an offset-aware UTC ISO-8601 timestamp."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_timestamp(value: str) -> datetime | None:
    """Parse a timestamp into UTC, returning ``None`` for invalid input."""

    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_public_url(value: str) -> str:
    """Return a safe absolute HTTP(S) URL or an empty marker.

    RSS entry links are external input. Reject non-web schemes, relative URLs,
    hostless URLs and malformed values instead of carrying them into canonical
    news evidence as if they were safe public links.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if parsed.scheme.lower() not in SAFE_PUBLIC_URL_SCHEMES:
        return ""
    if not parsed.hostname:
        return ""
    if port is not None and not (0 < port <= 65535):
        return ""
    return text


def normalize_publication_timestamp(
    published_at: str,
    *,
    fetched_at: datetime,
) -> tuple[str, str]:
    """Return canonical publication time and a truthful timestamp quality.

    Feed timestamps that are missing, malformed, or implausibly in the future
    are not trusted. They fail closed to the known fetch time instead of
    pretending to be source-origin timestamps.
    """

    fetched = fetched_at.astimezone(UTC) if fetched_at.tzinfo else fetched_at.replace(tzinfo=UTC)
    parsed = parse_timestamp(published_at)
    if parsed is None:
        return utc_iso(fetched), "fetch_fallback_missing_or_invalid"
    if parsed > fetched + MAX_FUTURE_SKEW:
        return utc_iso(fetched), "fetch_fallback_future_skew"
    return utc_iso(parsed), "source_timestamp"


def provenance_fields(
    *,
    source_id: str,
    source_name: str,
    source_feed_url: str,
    item_url: str,
    published_at: str,
    fetched_at: datetime,
) -> dict[str, str]:
    """Build compact canonical provenance fields for one news item."""

    canonical_published_at, timestamp_quality = normalize_publication_timestamp(
        published_at,
        fetched_at=fetched_at,
    )
    fetched_iso = utc_iso(fetched_at)
    family = str(source_id or "unknown").strip() or "unknown"
    safe_item_url = normalize_public_url(item_url)
    safe_feed_url = normalize_public_url(source_feed_url)
    identity = "\n".join(
        (
            family,
            safe_item_url,
            canonical_published_at,
        )
    ).encode("utf-8")
    provenance_id = hashlib.sha256(identity).hexdigest()
    return {
        "source_family": family,
        "source_feed_url": safe_feed_url,
        "source_name": str(source_name or "").strip(),
        "published_at": canonical_published_at,
        "fetched_at": fetched_iso,
        "timestamp_quality": timestamp_quality,
        "provenance_id": provenance_id,
    }


__all__ = [
    "MAX_FUTURE_SKEW",
    "SAFE_PUBLIC_URL_SCHEMES",
    "normalize_public_url",
    "normalize_publication_timestamp",
    "parse_timestamp",
    "provenance_fields",
    "utc_iso",
]
