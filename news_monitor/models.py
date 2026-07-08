"""Models for SharipovAI social/news monitoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NewsSource:
    """A monitored news or social source."""

    id: str
    name: str
    kind: str
    url: str
    trust_score: int
    category: str
    enabled: bool = True
    requires_credentials: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready source data."""

        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "url": self.url,
            "trust_score": self.trust_score,
            "category": self.category,
            "enabled": self.enabled,
            "requires_credentials": self.requires_credentials,
            "note": self.note,
        }


@dataclass(frozen=True)
class NewsItem:
    """A normalized news/social item."""

    source_id: str
    source_name: str
    kind: str
    title: str
    url: str
    published_at: str
    summary: str = ""
    symbols: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    trust_score: int = 50
    credibility_percent: int = 50
    error_risk: str = "повышенный"
    verification_status: str = "нужно подтверждение"
    urgency: str = "low"
    impact: str = "neutral"
    impact_score: int = 0
    needs_confirmation: bool = True
    confirmation_count: int = 1
    ai_action: str = "WATCH"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready item data."""

        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "summary": self.summary,
            "symbols": self.symbols,
            "tags": self.tags,
            "trust_score": self.trust_score,
            "credibility_percent": self.credibility_percent,
            "error_risk": self.error_risk,
            "verification_status": self.verification_status,
            "urgency": self.urgency,
            "impact": self.impact,
            "impact_score": self.impact_score,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_count": self.confirmation_count,
            "ai_action": self.ai_action,
            "reason": self.reason,
        }
