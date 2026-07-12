"""Typed evidence models for the existing SharipovAI News Intelligence organ."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
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

    def __post_init__(self) -> None:
        for name in ("article_id", "title", "source", "category", "published_at", "link", "language", "source_type"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_name.strip():
            raise ValueError("source identity is required")
        if self.requested_at_ms <= 0 or self.received_at_ms <= 0:
            raise ValueError("source timestamps must be positive")
        if self.received_at_ms < self.requested_at_ms:
            raise ValueError("received_at_ms must not precede requested_at_ms")
        if self.item_count < 0:
            raise ValueError("item_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def __post_init__(self) -> None:
        for name in ("agent_id", "agent_name", "category", "urgency", "impact", "detected_at"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        for name in ("sentiment", "relevance", "reliability", "score"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")

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


__all__ = ["NewsArticle", "NewsEnvelope", "SourceFetch"]
