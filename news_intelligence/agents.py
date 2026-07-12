"""Deterministic source-agent analysis for the existing News Intelligence organ."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .models import NewsArticle, NewsEnvelope, SourceFetch
from .sources import SourceDefinition


_POSITIVE = {"growth", "gain", "approval", "record", "surge", "recovery", "support"}
_NEGATIVE = {"loss", "ban", "fraud", "hack", "crash", "war", "sanction", "risk", "decline"}
_CRITICAL = {"hack", "exploit", "default", "war", "emergency", "ban"}
_HIGH = {"rate", "inflation", "sec", "regulation", "etf", "liquidation", "sanction"}


class SourceAgent:
    """One source-owned analyser; it never fetches data or submits trades."""

    def __init__(self, *, definition: SourceDefinition) -> None:
        self.definition = definition
        self._fingerprints: dict[str, str] = {}
        self._memory: deque[NewsEnvelope] = deque(maxlen=200)
        self._accepted = 0
        self._duplicates = 0

    def register(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope | None:
        if fetched.source_id != self.definition.source_id:
            raise ValueError("source fetch does not belong to this agent")
        if article.source != self.definition.name or article.category != self.definition.category:
            raise ValueError("article source identity does not match the agent")
        fingerprint = hashlib.sha256(
            json.dumps(article.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        previous = self._fingerprints.get(article.article_id)
        if previous is not None:
            if previous != fingerprint:
                raise RuntimeError(f"news article conflict: {article.article_id}")
            self._duplicates += 1
            return None

        envelope = self._analyse(article, fetched)
        self._fingerprints[article.article_id] = fingerprint
        self._memory.append(envelope)
        self._accepted += 1
        return envelope

    def memory(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        return [item.to_dict() for item in list(self._memory)[-bounded:]][::-1]

    def status(self) -> dict[str, Any]:
        return {
            "id": self.definition.source_id,
            "name": self.definition.name,
            "category": self.definition.category,
            "source_type": self.definition.source_type,
            "accepted": self._accepted,
            "duplicates": self._duplicates,
            "memory_count": len(self._memory),
            "read_only": True,
        }

    def _analyse(self, article: NewsArticle, fetched: SourceFetch) -> NewsEnvelope:
        text = f"{article.title} {article.summary}".lower()
        tokens = {token.strip(".,:;!?()[]{}\"'") for token in text.split()}
        positive = len(tokens & _POSITIVE)
        negative = len(tokens & _NEGATIVE)
        sentiment = max(-100.0, min(100.0, float((positive - negative) * 20)))
        reliability = 95.0 if fetched.verified and not fetched.error else 25.0
        relevance = 90.0 if article.category == self.definition.category else 50.0
        urgency = "critical" if tokens & _CRITICAL else "high" if tokens & _HIGH else "normal"
        impact = "positive" if sentiment > 0 else "negative" if sentiment < 0 else "neutral"
        urgency_weight = {"normal": 0.0, "high": 10.0, "critical": 20.0}[urgency]
        score = round(min(100.0, reliability * 0.45 + relevance * 0.35 + abs(sentiment) * 0.1 + urgency_weight), 4)
        reasons = [f"verified_source={fetched.verified}", f"category={article.category}"]
        if fetched.error:
            reasons.append(f"source_error={fetched.error}")
        if urgency != "normal":
            reasons.append(f"urgency={urgency}")
        detected_at = datetime.fromtimestamp(fetched.received_at_ms / 1000, UTC).isoformat()
        return NewsEnvelope(
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
            reasons=tuple(reasons),
            detected_at=detected_at,
        )


__all__ = ["SourceAgent"]
