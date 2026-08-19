"""Canonical, bounded provenance helpers for news ingress.

This module is intentionally pure and side-effect free.  It normalizes source
publication timestamps against the local fetch time and creates a compact stable
provenance identifier without storing raw feed payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

MAX_FUTURE_SKEW = timedelta(minutes=5)


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


def normalize_publication_timestamp(
    published_at: str,
    *,
    fetched_at: datetime,
) -> tuple[str, str]:
    """Return canonical publication time and a truthful timestamp quality.

    Feed timestamps that are missing, malformed, or implausibly in the future
    are not trusted.  They fail closed to the known fetch time instead of
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
    identity = "\n".join(
        (
            family,
            str(item_url or "").strip(),
            canonical_published_at,
        )
    ).encode("utf-8")
    provenance_id = hashlib.sha256(identity).hexdigest()
    return {
        "source_family": family,
        "source_feed_url": str(source_feed_url or "").strip(),
        "source_name": str(source_name or "").strip(),
        "published_at": canonical_published_at,
        "fetched_at": fetched_iso,
        "timestamp_quality": timestamp_quality,
        "provenance_id": provenance_id,
    }


__all__ = [
    "MAX_FUTURE_SKEW",
    "normalize_publication_timestamp",
    "parse_timestamp",
    "provenance_fields",
    "utc_iso",
]
