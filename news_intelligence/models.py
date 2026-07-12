"""Canonical data models for the DB-backed News Intelligence network."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NewsArticle:
    article_id: str
    title: str
    source: str
    category: str
    published_at: str
    link: str
    summary: str
    language: str
    source_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "source": self.source,
            "category": self.category,
            "published_at": self.published_at,
            "link": self.link,
            "summary": self.summary,
            "language": self.language,
            "source_type": self.source_type,
        }


@dataclass(frozen=True, slots=True)
class SourceFetch:
    source_id: str
    source_name: str
    source_type: str
    category: str
    requested_at_ms: int
    received_at_ms: int
    status_code: int
    verified: bool
    error: str
    item_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "category": self.category,
            "requested_at_ms": self.requested_at_ms,
            "received_at_ms": self.received_at_ms,
            "status_code": self.status_code,
            "verified": self.verified,
            "error": self.error,
            "item_count": self.item_count,
        }


@dataclass(frozen=True, slots=True)
class NewsEnvelope:
    agent_id: str
    agent_name: str
    category: str
    article: NewsArticle
    fetched: SourceFetch
    sentiment: float
    relevance: float
    reliability: float
    urgency: str
    impact: str
    score: float
    reasons: tuple[str, ...]
    detected_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "category": self.category,
            "article": self.article.to_dict(),
            "fetched": self.fetched.to_dict(),
            "sentiment": self.sentiment,
            "relevance": self.relevance,
            "reliability": self.reliability,
            "urgency": self.urgency,
            "impact": self.impact,
            "score": self.score,
            "reasons": list(self.reasons),
            "detected_at": self.detected_at,
        }
