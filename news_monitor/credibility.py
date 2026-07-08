"""Credibility scoring for news items.

The score is not a claim of absolute truth. It is an operational estimate of how
safe it is for SharipovAI to use a story in market analysis, based on source
reputation, source type, confirmations, urgency, and social-media risk.
"""

from __future__ import annotations

from typing import Iterable

LOW_RELIABILITY_KINDS = {"x", "telegram", "reddit", "youtube", "manual"}
HIGH_RELIABILITY_KINDS = {"official", "rss"}


def truth_probability(*, trust_score: int, kind: str, confirmation_count: int, urgency: str, tags: Iterable[str]) -> int:
    """Estimate truth probability from 1 to 99.

    This is a confidence score for the monitor, not a factual guarantee.
    """

    score = max(min(int(trust_score), 95), 5)
    normalized_kind = kind.lower().strip()
    normalized_tags = {tag.lower().strip() for tag in tags}

    if normalized_kind in LOW_RELIABILITY_KINDS:
        score -= 18
    if normalized_kind in HIGH_RELIABILITY_KINDS:
        score += 6
    if normalized_kind == "official":
        score += 7
    if confirmation_count >= 2:
        score += 10
    if confirmation_count >= 3:
        score += 8
    if urgency == "high" and confirmation_count < 2:
        score -= 12
    if "security" in normalized_tags or "liquidation" in normalized_tags:
        score -= 4
    if "regulation" in normalized_tags and confirmation_count < 2:
        score -= 6
    return max(min(score, 99), 1)


def error_risk(probability: int) -> str:
    """Return human-friendly error risk bucket."""

    if probability >= 85:
        return "низкий"
    if probability >= 70:
        return "средний"
    if probability >= 50:
        return "повышенный"
    return "высокий"


def verification_status(probability: int, confirmation_count: int, needs_confirmation: bool) -> str:
    """Return verification status for UI/API."""

    if probability >= 85 and confirmation_count >= 2 and not needs_confirmation:
        return "подтверждено"
    if probability >= 70 and confirmation_count >= 2:
        return "частично подтверждено"
    if needs_confirmation:
        return "нужно подтверждение"
    return "наблюдать"
