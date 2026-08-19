from datetime import datetime, timezone

import pytest

from learning.knowledge_evidence_v3 import KnowledgeEvidence, assess_knowledge_evidence


def _evidence(**overrides):
    values = {
        "fact_id": "FACT-1",
        "topic": "fees",
        "claim": "sample point-in-time claim",
        "source_url": "https://example.com/source",
        "source_domain": "example.com",
        "source_type": "official_documentation",
        "verified_at": "2026-08-19T10:00:00+00:00",
        "stale_after_seconds": 3600,
    }
    values.update(overrides)
    return KnowledgeEvidence(**values)


def test_current_evidence_never_has_execution_authority():
    result = assess_knowledge_evidence(
        _evidence(),
        as_of=datetime(2026, 8, 19, 10, 30, tzinfo=timezone.utc),
    )

    assert result["status"] == "CURRENT"
    assert result["usable_as_evidence"] is True
    assert result["execution_authority"] is False
    assert _evidence().to_dict()["execution_authority"] is False


def test_stale_evidence_fails_closed():
    result = assess_knowledge_evidence(
        _evidence(),
        as_of=datetime(2026, 8, 19, 11, 0, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "STALE"
    assert result["usable_as_evidence"] is False


def test_exchange_style_fact_requires_explicit_runtime_revalidation():
    evidence = _evidence(requires_runtime_revalidation=True)
    current = datetime(2026, 8, 19, 10, 20, tzinfo=timezone.utc)

    blocked = assess_knowledge_evidence(evidence, as_of=current)
    allowed = assess_knowledge_evidence(evidence, as_of=current, runtime_revalidated=True)

    assert blocked["status"] == "RUNTIME_REVALIDATION_REQUIRED"
    assert blocked["usable_as_evidence"] is False
    assert allowed["status"] == "CURRENT"
    assert allowed["execution_authority"] is False


def test_legal_style_fact_requires_explicit_manual_review():
    evidence = _evidence(topic="legal", requires_manual_review=True)
    current = datetime(2026, 8, 19, 10, 20, tzinfo=timezone.utc)

    blocked = assess_knowledge_evidence(evidence, as_of=current)
    allowed = assess_knowledge_evidence(evidence, as_of=current, manual_reviewed=True)

    assert blocked["status"] == "MANUAL_REVIEW_REQUIRED"
    assert blocked["usable_as_evidence"] is False
    assert allowed["status"] == "CURRENT"


def test_future_verification_and_future_effective_date_fail_closed():
    current = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)

    future_verified = assess_knowledge_evidence(
        _evidence(verified_at="2026-08-19T10:00:01+00:00"),
        as_of=current,
    )
    not_effective = assess_knowledge_evidence(
        _evidence(effective_from="2026-08-20T00:00:00+00:00"),
        as_of=current,
    )

    assert future_verified["status"] == "INVALID_FUTURE_VERIFICATION"
    assert future_verified["usable_as_evidence"] is False
    assert not_effective["status"] == "NOT_YET_EFFECTIVE"
    assert not_effective["usable_as_evidence"] is False


def test_contract_rejects_missing_provenance_and_naive_timestamps():
    with pytest.raises(ValueError, match="source_url is required"):
        _evidence(source_url="")
    with pytest.raises(ValueError, match="must include timezone"):
        _evidence(verified_at="2026-08-19T10:00:00")
    with pytest.raises(ValueError, match="must be positive"):
        _evidence(stale_after_seconds=0)
