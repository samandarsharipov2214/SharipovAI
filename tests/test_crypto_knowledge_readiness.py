from datetime import date

from ai_architecture_registry import CANONICAL_AI_ORGANS
from learning.crypto_knowledge_readiness import (
    FACTS,
    facts_for_organ,
    readiness_snapshot,
    score_exam,
)


def test_all_canonical_organs_receive_crypto_knowledge() -> None:
    organ_ids = {organ.id for organ in CANONICAL_AI_ORGANS}
    assert organ_ids == {
        "general_controller",
        "market_intelligence",
        "news_intelligence",
        "risk_engine",
        "portfolio_engine",
        "virtual_execution",
        "decision_quality",
        "learning_engine",
        "security_guard",
    }
    for organ_id in organ_ids:
        assert facts_for_organ(organ_id), organ_id


def test_knowledge_pack_is_ready_on_verification_date() -> None:
    snapshot = readiness_snapshot(today=date(2026, 8, 13))
    assert snapshot["status"] == "ready"
    assert snapshot["ready_organs"] == 9
    assert snapshot["total_organs"] == 9
    assert snapshot["execution_authority"] is False
    assert snapshot["live_trading_activation"] is False


def test_time_sensitive_sources_expire_fail_closed() -> None:
    snapshot = readiness_snapshot(today=date(2026, 9, 15))
    assert snapshot["status"] == "degraded"
    assert snapshot["ready_organs"] < 9
    assert any(
        organ["stale_fact_ids"]
        for organ in snapshot["organs"].values()
    )


def test_exchange_fee_facts_require_runtime_revalidation() -> None:
    fee_facts = [fact for fact in FACTS if fact.topic == "fees"]
    assert fee_facts
    assert all(fact.requires_runtime_revalidation for fact in fee_facts)


def test_live_legal_facts_require_manual_review() -> None:
    legal_or_tax = [fact for fact in FACTS if fact.topic in {"crypto_regulation", "tax"}]
    assert legal_or_tax
    assert all(fact.requires_manual_legal_review_before_live for fact in legal_or_tax)


def test_general_controller_can_pass_grounded_exam() -> None:
    result = score_exam(
        "general_controller",
        {
            "reg_limit": "300000",
            "payment": "нет",
            "tax": "13%",
            "cost": "нет",
        },
    )
    assert result["passed"] is True
    assert result["score_percent"] == 100.0
    assert result["execution_authority"] is False


def test_wrong_answer_fails_exam() -> None:
    result = score_exam(
        "risk_engine",
        {
            "reg_limit": "500000",
            "payment": "да",
            "tax": "22",
            "cost": "да",
        },
    )
    assert result["passed"] is False
    assert result["score_percent"] < 100.0
