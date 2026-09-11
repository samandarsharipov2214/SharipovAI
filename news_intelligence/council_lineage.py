"""Measurement-only provenance for the exact news rows consumed by Council.

Identical link hashes establish shared input, not independent information.
Different links do not establish independence (syndication remains unknown).
Neither these descriptors nor overlap counts authorize or reweight a vote.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _timestamp(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def news_memory_lineage(row: Mapping[str, Any]) -> dict[str, Any]:
    """Describe a captured NewsHub row without copying article text or URLs."""
    value = row.get("value") if isinstance(row.get("value"), Mapping) else {}
    article = value.get("article") if isinstance(value.get("article"), Mapping) else {}
    fetched = value.get("fetched") if isinstance(value.get("fetched"), Mapping) else {}
    link = _text(article.get("link"))
    return {
        "memory_namespace": "news_memory",
        "memory_updated_at_ms": _timestamp(row.get("updated_at_ms")),
        "fetch_received_at_ms": _timestamp(fetched.get("received_at_ms")),
        "source_id": _text(fetched.get("source_id")),
        "producer_id": _text(value.get("agent_id")),
        "article_id": _text(article.get("article_id")),
        "published_at": _text(article.get("published_at")),
        "exact_link_sha256": hashlib.sha256(link.encode("utf-8")).hexdigest() if link else None,
    }


def opinion_news_lineage(memories: Sequence[Mapping[str, Any]], *, now_ms: int) -> dict[str, Any]:
    """Preserve order and multiplicity of the provider's last-50 aggregation."""
    items = []
    for memory in memories[-50:]:
        raw = memory.get("source_lineage")
        raw = raw if isinstance(raw, Mapping) else {}
        item = {key: _text(raw.get(key)) for key in (
            "memory_namespace", "source_id", "producer_id", "article_id", "published_at", "exact_link_sha256",
        )}
        item.update({key: _timestamp(raw.get(key)) for key in ("memory_updated_at_ms", "fetch_received_at_ms")})
        item["memory_id"] = _text(memory.get("key"))
        item["lineage_error_type"] = _text(raw.get("error_type"))
        # These are the same already-normalized economic inputs seen by the vote.
        item.update({key: memory.get(key) for key in (
            "impact", "impact_score", "credibility_percent", "needs_confirmation",
        )})
        items.append(item)
    complete = sum(all(item.get(key) is not None for key in (
        "memory_id", "source_id", "article_id", "exact_link_sha256", "memory_updated_at_ms",
    )) for item in items)
    future = sum(item["memory_updated_at_ms"] is not None and item["memory_updated_at_ms"] > now_ms for item in items)
    known = any(item["source_id"] or item["article_id"] or item["exact_link_sha256"] for item in items)
    errors = sum(item["lineage_error_type"] is not None for item in items)
    return {
        "schema_version": 1,
        "status": "COMPLETE" if items and complete == len(items) else "PARTIAL" if known else "UNAVAILABLE",
        "captured_at_ms": now_ms,
        "eligible_memory_count": len(memories),
        "consumed_memory_count": len(items),
        "complete_lineage_count": complete,
        "rows_available_after_capture": future,
        "lineage_error_count": errors,
        "items": items,
        "symbol_relevance": "NOT_EVALUATED",
        "confidence_semantics": "impact-derived score; not calibrated probability or expected return",
        "feature_families": ["news_impact", "source_credibility", "confirmation_status"],
        "policy_influence": "NONE",
    }
