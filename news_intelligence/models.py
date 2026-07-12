"""Canonical immutable models for the DB-backed News Intelligence network."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def _required(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{name} is required")
    return clean


def _finite(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


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
    credibility_percent: float | None = None
    urgency: str = ""
    impact: str = ""
    impact_score: float = 0.0
    reason: str = ""
    symbols: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("article_id", "title", "source", "category", "published_at", "source_type"):
            _required(getattr(self, name), name)
        _finite(self.impact_score, "impact_score")
        if self.credibility_percent is not None:
            value = _finite(self.credibility_percent, "credibility_percent")
            if not 0.0 <= value <= 100.0:
                raise ValueError("credibility_percent must be between 0 and 100")

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
            "credibility_percent": self.credibility_percent,
            "urgency": self.urgency,
            "impact": self.impact,
            "impact_score": self.impact_score,
            "reason": self.reason,
            "symbols": list(self.symbols),
            "tags": list(self.tags),
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

    def __post_init__(self) -> None:
        for name in ("source_id", "source_name", "source_type", "category"):
            _required(getattr(self, name), name)
        if int(self.requested_at_ms) <= 0 or int(self.received_at_ms) <= 0:
            raise ValueError("source fetch timestamps must be positive")
        if int(self.received_at_ms) < int(self.requested_at_ms):
            raise ValueError("received_at_ms cannot precede requested_at_ms")
        if int(self.status_code) < 0:
            raise ValueError("status_code cannot be negative")
        if int(self.item_count) < 0:
            raise ValueError("item_count cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "category": self.category,
            "requested_at_ms": int(self.requested_at_ms),
            "received_at_ms": int(self.received_at_ms),
            "status_code": int(self.status_code),
            "verified": bool(self.verified),
            "error": self.error,
            "item_count": int(self.item_count),
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

    def __post_init__(self) -> None:
        for name in ("agent_id", "agent_name", "category", "urgency", "impact", "detected_at"):
            _required(getattr(self, name), name)
        for name in ("sentiment", "relevance", "reliability", "score"):
            value = _finite(getattr(self, name), name)
            if name != "sentiment" and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            if name == "sentiment" and not -1.0 <= value <= 1.0:
                raise ValueError("sentiment must be between -1 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "category": self.category,
            "article": self.article.to_dict(),
            "fetched": self.fetched.to_dict(),
            "sentiment": float(self.sentiment),
            "relevance": float(self.relevance),
            "reliability": float(self.reliability),
            "urgency": self.urgency,
            "impact": self.impact,
            "score": float(self.score),
            "reasons": list(self.reasons),
            "detected_at": self.detected_at,
        }


__all__ = ["NewsArticle", "NewsEnvelope", "SourceFetch"]
