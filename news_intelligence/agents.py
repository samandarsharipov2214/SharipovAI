"""Per-source analysis agents for the canonical News Intelligence network."""
from __future__ import annotations

import os
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .models import NewsArticle, NewsEnvelope, SourceFetch
from .sources import SourceDefinition

_POSITIVE = {"approval", "approved", "growth", "gain", "inflow", "rally", "record", "support", "surge", "upgrade"}
_NEGATIVE = {"attack", "ban", "breach", "crash", "decline", "exploit", "hack", "lawsuit", "loss", "outflow", "sanction"}
_CRITICAL = {"attack", "breach", "emergency", "exploit", "hack", "liquidation", "sanction"}
_HIGH = {"breaking", "central bank", "inflation", "lawsuit", "regulation", "sec", "rate", "warning"}
_MARKET = {"bitcoin", "btc", "crypto", "ethereum", "eth", "exchange", "market", "monetary", "rate", "regulation", "security"}


class SourceAgent:
    def __init__(self, *, definition: SourceDefinition) -> None:
        self.definition = definition
        memory_limit = _bounded_int("NEWS_AGENT_SOURCE_MEMORY_LIMIT", default=200, minimum=20, maximum=2000)
        self._memory: deque[NewsEnvelope] = deque(maxlen=memory_limit)
        self._seen: set[str] = set()
        self._processed = 0
        self._duplicates = 0
        self._last_error = ""
        self._last_action = "waiting"
        self._last_seen_at = ""

    def register(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope | None:
        if article.article_id in self._seen:
            self._duplicates += 1
            self._last_action = "duplicate_ignored"
            return None
        self._validate(article, fetched)

        text = f"{article.title} {article.summary}".lower()
        positive = sum(1 for token in _POSITIVE if token in text)
        negative = sum(1 for token in _NEGATIVE if token in text)
        sentiment = _clamp((positive - negative) / max(positive + negative, 1), -1.0, 1.0)
        relevance_hits = sum(1 for token in _MARKET if token in text)
        relevance = _clamp(0.35 + relevance_hits * 0.1, 0.0, 1.0)
        base_reliability = _clamp(self.definition.trust_score / 100.0, 0.01, 0.99)
        reliability = base_reliability if fetched.verified and not fetched.error else _clamp(base_reliability - 0.35, 0.01, 0.99)

        critical_hits = [token for token in _CRITICAL if token in text]
        high_hits = [token for token in _HIGH if token in text]
        if critical_hits and relevance >= 0.45:
            urgency = "critical"
        elif high_hits or abs(sentiment) >= 0.75:
            urgency = "high"
        elif relevance >= 0.55:
            urgency = "medium"
        else:
            urgency = "low"

        if sentiment > 0.15:
            impact = "bullish"
        elif sentiment < -0.15:
            impact = "bearish"
        else:
            impact = "neutral"

        score = round(_clamp(reliability * 0.5 + relevance * 0.35 + abs(sentiment) * 0.15, 0.0, 1.0), 6)
        reasons = [
            f"source_trust={self.definition.trust_score}",
            f"verified_fetch={str(fetched.verified).lower()}",
            f"market_keyword_hits={relevance_hits}",
        ]
        if critical_hits:
            reasons.append("critical_terms=" + ",".join(sorted(critical_hits)))
        elif high_hits:
            reasons.append("high_terms=" + ",".join(sorted(high_hits)))
        if fetched.error:
            reasons.append(f"fetch_error={fetched.error}")

        detected_at = datetime.fromtimestamp(max(fetched.received_at_ms, 1) / 1000, tz=UTC).isoformat()
        envelope = NewsEnvelope(
            agent_id=self.definition.source_id,
            agent_name=self.definition.name,
            category=self.definition.category,
            article=article,
            fetched=fetched,
            sentiment=round(sentiment, 6),
            relevance=round(relevance, 6),
            reliability=round(reliability, 6),
            urgency=urgency,
            impact=impact,
            score=score,
            reasons=tuple(reasons),
            detected_at=detected_at,
        )
        self._seen.add(article.article_id)
        self._memory.append(envelope)
        self._processed += 1
        self._last_error = fetched.error
        self._last_action = "article_registered"
        self._last_seen_at = detected_at
        return envelope

    def memory(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        return [item.to_dict() for item in list(self._memory)[-bounded:]][::-1]

    def status(self) -> dict[str, Any]:
        if self._last_error:
            status = "degraded"
        elif self._processed:
            status = "active"
        else:
            status = "idle"
        return {
            "source_id": self.definition.source_id,
            "id": self.definition.source_id,
            "name": self.definition.name,
            "source_name": self.definition.name,
            "source_type": self.definition.source_type,
            "category": self.definition.category,
            "status": status,
            "processed": self._processed,
            "duplicates": self._duplicates,
            "memory_count": len(self._memory),
            "last_action": self._last_action,
            "last_error": self._last_error,
            "last_seen_at": self._last_seen_at,
            "trust_score": self.definition.trust_score,
        }

    def _validate(self, article: NewsArticle, fetched: SourceFetch) -> None:
        if not article.article_id or not article.title or not article.link:
            raise ValueError("news article requires article_id, title and link")
        if fetched.source_id != self.definition.source_id:
            raise ValueError("fetch source_id does not match agent definition")
        if article.category != self.definition.category:
            raise ValueError("article category does not match agent definition")
        if fetched.received_at_ms < fetched.requested_at_ms:
            raise ValueError("source fetch received_at_ms cannot precede requested_at_ms")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(float(value), minimum), maximum)


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
