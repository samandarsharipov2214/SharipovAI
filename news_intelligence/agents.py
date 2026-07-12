"""Deterministic source agents for canonical News Intelligence."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .models import NewsArticle, NewsEnvelope, SourceFetch
from .sources import SourceDefinition

_POSITIVE = (
    "approval", "approved", "adoption", "partnership", "inflow", "upgrade",
    "buyback", "listing", "growth", "rise", "рост", "одобр", "листинг", "приток",
)
_NEGATIVE = (
    "hack", "exploit", "lawsuit", "ban", "outflow", "delisting", "liquidation",
    "breach", "банкрот", "взлом", "иск", "запрет", "ликвидац", "делист",
)
_CRITICAL = ("emergency", "critical", "exploit", "hack", "halt", "срочно", "взлом", "останов")
_HIGH = ("breaking", "urgent", "alert", "warning", "maintenance", "предупреж", "авар")


class SourceAgent:
    def __init__(self, *, definition: SourceDefinition) -> None:
        self.definition = definition
        limit = _bounded_int("NEWS_AGENT_SOURCE_MEMORY_LIMIT", 200, 20, 5000)
        self._memory: deque[NewsEnvelope] = deque(maxlen=limit)
        self._fingerprints: dict[str, str] = {}
        self._accepted = 0
        self._duplicates = 0
        self._last_error = ""
        self._last_action = "waiting_for_verified_items"

    def register(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope | None:
        fingerprint = _fingerprint(article, fetched)
        previous = self._fingerprints.get(article.article_id)
        if previous is not None:
            if previous == fingerprint:
                self._duplicates += 1
                self._last_action = "duplicate_ignored"
                return None
            self._last_error = f"article identity conflict: {article.article_id}"
            raise RuntimeError(self._last_error)

        if fetched.source_id != self.definition.source_id:
            self._last_error = "source fetch does not belong to this agent"
            raise ValueError(self._last_error)

        sentiment = _sentiment(article)
        reliability = _reliability(article, self.definition, fetched)
        relevance = 1.0 if article.category == self.definition.category else 0.65
        urgency = _urgency(article)
        impact = _impact(article, sentiment)
        score = _clamp(reliability * 0.55 + relevance * 0.30 + min(abs(sentiment), 1.0) * 0.15)
        reasons = _reasons(article, fetched, relevance, reliability)
        detected_at = datetime.fromtimestamp(fetched.received_at_ms / 1000, tz=UTC).isoformat()

        envelope = NewsEnvelope(
            agent_id=self.definition.source_id,
            agent_name=self.definition.name,
            category=self.definition.category,
            article=article,
            fetched=fetched,
            sentiment=sentiment,
            relevance=relevance,
            reliability=reliability,
            urgency=urgency,
            impact=impact,
            score=score,
            reasons=reasons,
            detected_at=detected_at,
        )
        self._fingerprints[article.article_id] = fingerprint
        self._memory.append(envelope)
        self._accepted += 1
        self._last_error = fetched.error
        self._last_action = "verified_article_registered" if fetched.verified else "unverified_article_quarantined"
        return envelope

    def memory(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in reversed(self._memory)]

    def status(self) -> dict[str, Any]:
        if self._last_error:
            status = "error"
        elif self._accepted:
            status = "active"
        else:
            status = "idle"
        return {
            "id": self.definition.source_id,
            "source_id": self.definition.source_id,
            "name": self.definition.name,
            "source_name": self.definition.name,
            "source_type": self.definition.source_type,
            "category": self.definition.category,
            "status": status,
            "trust_score": int(self.definition.trust_score),
            "requires_credentials": bool(self.definition.requires_credentials),
            "accepted_count": self._accepted,
            "duplicate_count": self._duplicates,
            "memory_count": len(self._memory),
            "last_error": self._last_error,
            "last_action": self._last_action,
            "synthetic_fallback_used": False,
        }


def _fingerprint(article: NewsArticle, fetched: SourceFetch) -> str:
    stable_fetch = fetched.to_dict()
    stable_fetch.pop("requested_at_ms", None)
    stable_fetch.pop("received_at_ms", None)
    raw = json.dumps(
        {"article": article.to_dict(), "fetch": stable_fetch},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sentiment(article: NewsArticle) -> float:
    declared = str(article.impact).strip().lower()
    declared_score = _clamp(float(article.impact_score) / 100.0, -1.0, 1.0)
    if declared in {"bullish", "positive", "рост"}:
        return declared_score if declared_score > 0 else 0.5
    if declared in {"bearish", "negative", "падение"}:
        return declared_score if declared_score < 0 else -0.5
    text = f"{article.title} {article.summary}".lower()
    positive = sum(1 for value in _POSITIVE if value in text)
    negative = sum(1 for value in _NEGATIVE if value in text)
    return _clamp((positive - negative) * 0.25, -1.0, 1.0)


def _reliability(article: NewsArticle, definition: SourceDefinition, fetched: SourceFetch) -> float:
    raw = article.credibility_percent
    percent = float(definition.trust_score if raw is None else raw)
    value = _clamp(percent / 100.0)
    if not fetched.verified:
        value = min(value, 0.49)
    if fetched.error:
        value = min(value, 0.25)
    return value


def _urgency(article: NewsArticle) -> str:
    declared = str(article.urgency).strip().lower()
    if declared in {"low", "medium", "high", "critical"}:
        return declared
    text = f"{article.title} {article.summary}".lower()
    if any(value in text for value in _CRITICAL):
        return "critical"
    if any(value in text for value in _HIGH):
        return "high"
    return "medium" if abs(float(article.impact_score)) >= 40 else "low"


def _impact(article: NewsArticle, sentiment: float) -> str:
    declared = str(article.impact).strip().lower()
    if declared in {"bullish", "bearish", "neutral"}:
        return declared
    if sentiment > 0:
        return "bullish"
    if sentiment < 0:
        return "bearish"
    return "neutral"


def _reasons(
    article: NewsArticle,
    fetched: SourceFetch,
    relevance: float,
    reliability: float,
) -> tuple[str, ...]:
    values = [
        "real_saved_news_only",
        f"source_verified={str(bool(fetched.verified)).lower()}",
        f"reliability={reliability:.3f}",
        f"category_match={str(relevance == 1.0).lower()}",
    ]
    if article.reason:
        values.append(article.reason)
    if fetched.error:
        values.append(f"source_error={fetched.error}")
    return tuple(values)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        return minimum
    return min(max(parsed, minimum), maximum)


__all__ = ["SourceAgent"]
