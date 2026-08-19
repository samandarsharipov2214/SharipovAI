"""Bounded event identity and source-family clustering for news evidence.

The layer is deliberately conservative: only items with the same normalized
headline and UTC publication day share an event id.  Distinct source families
are counted separately, while repeated items from the same family never inflate
the family count.  A distinct family is not claimed to prove editorial
independence; it is only a machine-verifiable prerequisite for later source
independence policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import html
import re
import unicodedata
from typing import Any

DEFAULT_MAX_ITEMS = 512
_EVENT_ID_VERSION = "news-event-v1"
_NON_WORD = re.compile(r"[^\w]+", flags=re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_headline(value: str) -> str:
    """Return a deterministic headline fingerprint input."""

    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def publication_day(value: str) -> str:
    """Return canonical UTC YYYY-MM-DD or an empty marker for invalid input."""

    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date().isoformat()


def event_id_for_item(item: Mapping[str, Any]) -> str:
    """Create a stable conservative event id for one normalized news item."""

    headline = normalize_headline(str(item.get("title") or ""))
    if not headline:
        provenance_id = str(item.get("provenance_id") or "").strip()
        if provenance_id:
            return hashlib.sha256(
                f"{_EVENT_ID_VERSION}\nprovenance\n{provenance_id}".encode("utf-8")
            ).hexdigest()
        raise ValueError("news item requires title or provenance_id for event identity")
    day = publication_day(str(item.get("published_at") or ""))
    payload = f"{_EVENT_ID_VERSION}\nheadline-day\n{day}\n{headline}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cluster_news_events(
    items: Sequence[Mapping[str, Any]],
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict[str, object]:
    """Cluster a bounded item set into compact event records.

    The returned records contain only compact identity/provenance references;
    raw summaries or feed payloads are intentionally not copied into the event
    layer.  ``source_family_count`` counts distinct declared publisher families
    and must not be interpreted as proof of editorial independence.
    """

    limit = int(max_items)
    if limit < 1:
        raise ValueError("max_items must be positive")

    selected = list(items[:limit])
    clusters: dict[str, dict[str, object]] = {}
    for item in selected:
        event_id = event_id_for_item(item)
        family = str(item.get("source_family") or item.get("source_id") or "unknown").strip() or "unknown"
        provenance_id = str(item.get("provenance_id") or "").strip()
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        published_at = str(item.get("published_at") or "").strip()
        trust_score = _finite_score(item.get("trust_score"))

        cluster = clusters.get(event_id)
        if cluster is None:
            cluster = {
                "event_id": event_id,
                "event_identity_version": _EVENT_ID_VERSION,
                "title": title,
                "published_day": publication_day(published_at),
                "representative_url": url,
                "representative_trust_score": trust_score,
                "item_count": 0,
                "source_families": set(),
                "provenance_ids": set(),
            }
            clusters[event_id] = cluster

        cluster["item_count"] = int(cluster["item_count"]) + 1
        families = cluster["source_families"]
        assert isinstance(families, set)
        families.add(family)
        if provenance_id:
            provenance_ids = cluster["provenance_ids"]
            assert isinstance(provenance_ids, set)
            provenance_ids.add(provenance_id)

        current_score = float(cluster["representative_trust_score"])
        if trust_score > current_score:
            cluster["title"] = title
            cluster["representative_url"] = url
            cluster["representative_trust_score"] = trust_score

    events: list[dict[str, object]] = []
    for cluster in clusters.values():
        families = tuple(sorted(str(value) for value in cluster.pop("source_families")))
        provenance_ids = tuple(sorted(str(value) for value in cluster.pop("provenance_ids")))
        events.append(
            {
                **cluster,
                "source_families": families,
                "source_family_count": len(families),
                "provenance_ids": provenance_ids,
            }
        )
    events.sort(key=lambda row: (str(row["published_day"]), str(row["event_id"])), reverse=True)
    return {
        "events": events,
        "input_item_count": len(items),
        "processed_item_count": len(selected),
        "event_count": len(events),
        "truncated": len(items) > limit,
        "max_items": limit,
    }


def _finite_score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return 0.0
    return parsed


__all__ = [
    "DEFAULT_MAX_ITEMS",
    "cluster_news_events",
    "event_id_for_item",
    "normalize_headline",
    "publication_day",
]
