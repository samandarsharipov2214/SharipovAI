"""Per-source News Intelligence agents.

The agent derives transparent heuristic fields from real fetched articles and
keeps a bounded in-memory cache.  Durable evidence is written by ``NewsHub`` to
ProjectDatabase.
"""
from __future__ import annotations

import math
import os
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .models import NewsArticle, NewsEnvelope, SourceFetch
from .sources import SourceDefinition

_BULLISH = (
    "approval", "approved", "adoption", "inflow", "partnership", "upgrade",
    "listing", "listed", "buyback", "record high", "growth", "surge",
)
_BEARISH = (
    "hack", "exploit", "ban", "lawsuit", "delisting", "outflow", "liquidation",
    "bankruptcy", "default", "fraud", "breach", "attack", "sanction",
)
_URGENT = (
    "breaking", "urgent", "alert", "hack", "exploit", "halt", "emergency",
    "liquidation", "delisting", "attack",
)
_MARKET_TERMS = (
    "bitcoin", "btc", "ethereum", "eth", "crypto", "market", "inflation", "rate",
    "fed", "sec", "treasury", "exchange", "liquidity", "etf", "stablecoin",
)


class SourceAgent:
    """Analyze articles from one configured source and expose runtime evidence."""

    def __init__(self, *, definition: SourceDefinition) -> None:
        self.definition = definition
        limit = _bounded_int("NEWS_AGENT_LOCAL_MEMORY_LIMIT", default=100, minimum=20, maximum=1000)
        self._memory: deque[NewsEnvelope] = deque(maxlen=limit)
        self._seen: set[str] = set()
        self._status = "idle"
        self._last_action = "ожидание первого реального RSS-цикла"
        self._last_error = ""
        self._last_seen_at_ms = 0
        self._accepted = 0
        self._duplicates = 0

    def register(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope | None:
        self._last_seen_at_ms = int(time.time() * 1000)
        if article.article_id in self._seen:
            self._duplicates += 1
            self._status = "active"
            self._last_action = "повторная статья пропущена как дубликат"
            return None

        envelope = _analyze(self.definition, article, fetched)
        self._seen.add(article.article_id)
        self._memory.append(envelope)
        self._accepted += 1
        self._status = "active" if fetched.verified else "degraded"
        self._last_error = fetched.error
        self._last_action = (
            f"принята реальная статья: urgency={envelope.urgency}, impact={envelope.impact}, "
            f"score={envelope.score:.1f}"
        )
        self._trim_seen()
        return envelope

    def status(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        age_seconds = None if not self._last_seen_at_ms else max(0, (now_ms - self._last_seen_at_ms) // 1000)
        status = self._status
        if age_seconds is not None and age_seconds > 3 * 3600 and status == "active":
            status = "stale"
        return {
            "source_id": self.definition.source_id,
            "name": self.definition.name,
            "category": self.definition.category,
            "source_type": self.definition.source_type,
            "url": self.definition.url,
            "trust_score": self.definition.trust_score,
            "status": status,
            "last_action": self._last_action,
            "last_error": self._last_error,
            "last_seen_at_ms": self._last_seen_at_ms,
            "heartbeat_age_seconds": age_seconds,
            "accepted": self._accepted,
            "duplicates": self._duplicates,
            "memory_size": len(self._memory),
            "synthetic_fallback_used": False,
        }

    def memory(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in reversed(self._memory)]

    def _trim_seen(self) -> None:
        maximum = max(self._memory.maxlen * 4, 100)
        if len(self._seen) <= maximum:
            return
        self._seen = {item.article.article_id for item in self._memory}


def _analyze(definition: SourceDefinition, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope:
    text = f"{article.title} {article.summary}".lower()
    bullish = sum(1 for word in _BULLISH if word in text)
    bearish = sum(1 for word in _BEARISH if word in text)
    polarity = bullish - bearish
    sentiment = _clamp(polarity / max(bullish + bearish, 1), -1.0, 1.0)

    market_hits = sum(1 for word in _MARKET_TERMS if word in text)
    relevance = _clamp(0.25 + market_hits * 0.09, 0.0, 1.0)
    reliability = _clamp(float(definition.trust_score) / 100.0, 0.0, 1.0)
    if not fetched.verified:
        reliability = min(reliability, 0.25)

    urgent_hits = sum(1 for word in _URGENT if word in text)
    urgency = "critical" if urgent_hits >= 2 and reliability >= 0.7 else "high" if urgent_hits else "medium" if abs(sentiment) >= 0.5 else "low"
    impact = "bullish" if sentiment > 0.15 else "bearish" if sentiment < -0.15 else "neutral"
    urgency_weight = {"low": 0.25, "medium": 0.5, "high": 0.8, "critical": 1.0}[urgency]
    score = round(_clamp((relevance * 0.35 + reliability * 0.4 + urgency_weight * 0.25) * 100.0, 0.0, 100.0), 2)

    reasons = [
        f"source_trust={definition.trust_score}",
        f"market_term_hits={market_hits}",
        f"urgent_term_hits={urgent_hits}",
        f"bullish_terms={bullish}",
        f"bearish_terms={bearish}",
        f"fetch_verified={fetched.verified}",
    ]
    return NewsEnvelope(
        agent_id=definition.source_id,
        agent_name=definition.name,
        category=definition.category,
        article=article,
        fetched=fetched,
        sentiment=round(sentiment, 4),
        relevance=round(relevance, 4),
        reliability=round(reliability, 4),
        urgency=urgency,
        impact=impact,
        score=score,
        reasons=tuple(reasons),
        detected_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if not math.isfinite(value):
        return minimum
    return min(max(value, minimum), maximum)


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["SourceAgent"]
