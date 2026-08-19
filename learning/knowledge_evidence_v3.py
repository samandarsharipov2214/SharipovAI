"""Passive freshness-bound knowledge evidence for SharipovAI V3.

This module modernizes the useful contract from stale PR #273 without copying
point-in-time legal, tax, or exchange-fee claims into current main. Facts are
versioned evidence only. They never gain execution authority, and callers must
explicitly satisfy any runtime-revalidation or manual-review requirement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class KnowledgeEvidence:
    fact_id: str
    topic: str
    claim: str
    source_url: str
    source_domain: str
    source_type: str
    verified_at: str
    stale_after_seconds: int
    jurisdiction: str = "global"
    effective_from: str | None = None
    requires_runtime_revalidation: bool = False
    requires_manual_review: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "fact_id",
            "topic",
            "claim",
            "source_url",
            "source_domain",
            "source_type",
            "verified_at",
            "jurisdiction",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        _parse_utc(self.verified_at)
        if self.effective_from is not None:
            _parse_utc(self.effective_from)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "execution_authority": False}


def assess_knowledge_evidence(
    evidence: KnowledgeEvidence,
    *,
    as_of: datetime | None = None,
    runtime_revalidated: bool = False,
    manual_reviewed: bool = False,
) -> dict[str, Any]:
    """Return a fail-closed usability assessment for one evidence fact."""

    current = as_of or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    current = current.astimezone(timezone.utc)
    verified = _parse_utc(evidence.verified_at)
    if verified > current:
        return _assessment(evidence, current, "INVALID_FUTURE_VERIFICATION", False)

    if evidence.effective_from is not None and _parse_utc(evidence.effective_from) > current:
        return _assessment(evidence, current, "NOT_YET_EFFECTIVE", False)

    age_seconds = int((current - verified).total_seconds())
    if age_seconds > evidence.stale_after_seconds:
        return _assessment(evidence, current, "STALE", False, age_seconds=age_seconds)

    if evidence.requires_runtime_revalidation and not runtime_revalidated:
        return _assessment(evidence, current, "RUNTIME_REVALIDATION_REQUIRED", False, age_seconds=age_seconds)

    if evidence.requires_manual_review and not manual_reviewed:
        return _assessment(evidence, current, "MANUAL_REVIEW_REQUIRED", False, age_seconds=age_seconds)

    return _assessment(evidence, current, "CURRENT", True, age_seconds=age_seconds)


def _assessment(
    evidence: KnowledgeEvidence,
    current: datetime,
    status: str,
    usable: bool,
    *,
    age_seconds: int | None = None,
) -> dict[str, Any]:
    return {
        "fact_id": evidence.fact_id,
        "topic": evidence.topic,
        "status": status,
        "usable_as_evidence": usable,
        "age_seconds": age_seconds,
        "assessed_at": current.isoformat(),
        "source_url": evidence.source_url,
        "source_domain": evidence.source_domain,
        "requires_runtime_revalidation": evidence.requires_runtime_revalidation,
        "requires_manual_review": evidence.requires_manual_review,
        "execution_authority": False,
    }


def _parse_utc(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamps must include timezone")
    return parsed.astimezone(timezone.utc)


__all__ = ["KnowledgeEvidence", "assess_knowledge_evidence"]
