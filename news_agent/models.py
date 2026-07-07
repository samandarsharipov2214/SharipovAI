"""Typed models for news analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsClassification:
    """Deterministic news classification result.

    Attributes:
        category: Classified news category.
        sentiment: Classified sentiment.
        impact_score: Deterministic impact score from 0 to 100.
    """

    category: str
    sentiment: str
    impact_score: float


@dataclass(frozen=True, slots=True)
class NewsAnalysis:
    """Structured analysis for one news item.

    Attributes:
        headline: News headline.
        category: Classified news category.
        sentiment: Classified sentiment.
        impact_score: Deterministic impact score from 0 to 100.
        reason: Human-readable analysis reason.
    """

    headline: str
    category: str
    sentiment: str
    impact_score: float
    reason: str
