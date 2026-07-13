"""Typed evidence models used by the canonical News Intelligence runtime."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


def _text(value: Any, name: str, *, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{name} is required")
    return result


def _positive(value: Any, name: str) -> int:
    result = int(value)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _finite(value: Any, name: str, *, minimum: float = -1.0, maximum: float = 1.0) -> float:
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    return result


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
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "summary", _text(self.summary, "summary", required=False))

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
        for name in ("source_id", "source_name", "source_type", "category"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "requested_at_ms", _positive(self.requested_at_ms, "requested_at_ms"))
        object.__setattr__(self, "received_at_ms", _positive(self.received_at_ms, "received_at_ms"))
        if self.received_at_ms < self.requested_at_ms:
            raise ValueError("received_at_ms cannot precede requested_at_ms")
        object.__setattr__(self, "status_code", max(int(self.status_code), 0))
        object.__setattr__(self, "verified", bool(self.verified))
        object.__setattr__(self, "error", _text(self.error, "error", required=False))
        object.__setattr__(self, "item_count", max(int(self.item_count), 0))

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
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.article, NewsArticle):
            raise TypeError("article must be NewsArticle")
        if not isinstance(self.fetched, SourceFetch):
            raise TypeError("fetched must be SourceFetch")
        object.__setattr__(self, "sentiment", _finite(self.sentiment, "sentiment"))
        object.__setattr__(self, "relevance", _finite(self.relevance, "relevance", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "reliability", _finite(self.reliability, "reliability", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "score", _finite(self.score, "score", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "reasons", tuple(_text(item, "reason") for item in self.reasons))

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
