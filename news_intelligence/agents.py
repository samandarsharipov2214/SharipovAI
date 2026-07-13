"""Deterministic source agents for the canonical News Intelligence network.

Agents never invent articles. They only score and wrap evidence returned by a
configured source collector.
"""
from __future__ import annotations

import os
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .models import NewsArticle, NewsEnvelope, SourceFetch
from .sources import SourceDefinition

_POSITIVE = {
    "growth", "gain", "gains", "rise", "rises", "approval", "approved",
    "recovery", "surge", "record", "profit", "profits", "bullish", "peace",
}
_NEGATIVE = {
    "loss", "losses", "fall", "falls", "drop", "drops", "crash", "war",
    "attack", "sanction", "sanctions", "fraud", "hack", "hacked", "default",
    "bankruptcy", "emergency", "inflation", "recession", "bearish",
}
_CRITICAL = {
    "emergency", "attack", "war", "explosion", "default", "bankruptcy",
    "hack", "hacked", "shutdown", "earthquake", "tsunami", "evacuation",
}
_HIGH = {
    "breaking", "urgent", "central bank", "interest rate", "inflation",
    "sanction", "sec", "regulator", "election", "ceasefire", "outage",
}
_MARKET = {
    "bitcoin", "btc", "ethereum", "eth", "crypto", "market", "exchange",
    "stock", "stocks", "bond", "bonds", "bank", "central bank", "rate",
    "inflation", "economy", "economic", "oil", "gas", "gold", "dollar",
}


class SourceAgent:
    def __init__(self, *, definition: SourceDefinition) -> None:
        if not isinstance(definition, SourceDefinition):
            raise TypeError("definition must be SourceDefinition")
        self.definition = definition
        limit = _bounded_int("NEWS_AGENT_LOCAL_MEMORY", 200, 20, 2000)
        self._memory: deque[NewsEnvelope] = deque(maxlen=limit)
        self._seen: set[str] = set()
        self._last_action = "waiting"
        self._last_error = ""
        self._last_seen_at_ms = 0
        self._registered_count = 0
        self._duplicate_count = 0

    def register(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope | None:
        if not isinstance(article, NewsArticle) or not isinstance(fetched, SourceFetch):
            raise TypeError("article and fetched evidence are required")
        if fetched.source_id != self.definition.source_id:
            raise ValueError("source fetch does not belong to this agent")
        if article.article_id in self._seen:
            self._duplicate_count += 1
            self._last_action = "duplicate_skipped"
            return None

        try:
            envelope = self._build_envelope(article, fetched)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._last_action = "analysis_failed"
            raise

        self._seen.add(article.article_id)
        self._memory.append(envelope)
        self._registered_count += 1
        self._last_seen_at_ms = fetched.received_at_ms
        self._last_action = "article_analyzed"
        self._last_error = ""
        return envelope

    def memory(self, limit: int = 100) -> list[dict[str, Any]]:
        count = max(1, min(int(limit), 1000))
        return [item.to_dict() for item in list(self._memory)[-count:]][::-1]

    def status(self) -> dict[str, Any]:
        age_seconds = None
        if self._last_seen_at_ms > 0:
            age_seconds = max((int(time.time() * 1000) - self._last_seen_at_ms) / 1000.0, 0.0)
        return {
            "id": self.definition.source_id,
            "source_id": self.definition.source_id,
            "name": self.definition.name,
            "source_name": self.definition.name,
            "source_type": self.definition.source_type,
            "category": self.definition.category,
            "status": "error" if self._last_error else "active" if self._last_seen_at_ms else "idle",
            "verified_source": self.definition.verified,
            "reliability": self.definition.reliability,
            "registered_count": self._registered_count,
            "duplicate_count": self._duplicate_count,
            "memory_count": len(self._memory),
            "last_seen_at_ms": self._last_seen_at_ms,
            "data_freshness_seconds": age_seconds,
            "last_action": self._last_action,
            "last_error": self._last_error,
        }

    def _build_envelope(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope:
        text = f"{article.title} {article.summary}".lower()
        words = {token.strip(".,:;!?()[]{}\"'") for token in text.split() if token.strip()}
        positive = sum(1 for token in _POSITIVE if token in text)
        negative = sum(1 for token in _NEGATIVE if token in text)
        sentiment = max(-1.0, min(1.0, (positive - negative) / max(positive + negative, 3)))

        market_hits = sum(1 for token in _MARKET if token in text)
        relevance = min(1.0, 0.30 + market_hits * 0.12 + (0.12 if article.category == self.definition.category else 0.0))
        reliability = self.definition.reliability if fetched.verified else min(self.definition.reliability, 0.35)

        critical_hits = [token for token in _CRITICAL if token in text]
        high_hits = [token for token in _HIGH if token in text]
        if critical_hits:
            urgency = "critical"
        elif high_hits:
            urgency = "high"
        elif market_hits:
            urgency = "medium"
        else:
            urgency = "low"

        if market_hits >= 3 or urgency == "critical":
            impact = "high"
        elif market_hits or urgency == "high":
            impact = "medium"
        else:
            impact = "low"

        urgency_weight = {"low": 0.20, "medium": 0.45, "high": 0.72, "critical": 1.0}[urgency]
        score = min(1.0, max(0.0, relevance * 0.45 + reliability * 0.40 + urgency_weight * 0.15))
        reasons = [
            f"source_reliability={reliability:.2f}",
            f"market_terms={market_hits}",
            f"sentiment={sentiment:.2f}",
        ]
        if critical_hits:
            reasons.append("critical_terms=" + ",".join(sorted(critical_hits)))
        elif high_hits:
            reasons.append("high_priority_terms=" + ",".join(sorted(high_hits)))
        if not fetched.verified:
            reasons.append("source_fetch_not_verified")

        detected_at = datetime.fromtimestamp(fetched.received_at_ms / 1000, tz=UTC).isoformat()
        return NewsEnvelope(
            agent_id=self.definition.source_id,
            agent_name=self.definition.name,
            category=self.definition.category,
            article=article,
            fetched=fetched,
            sentiment=round(sentiment, 4),
            relevance=round(relevance, 4),
            reliability=round(reliability, 4),
            urgency=urgency,
            impact=impact,
            score=round(score, 4),
            reasons=tuple(reasons),
            detected_at=detected_at,
        )


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["SourceAgent"]
