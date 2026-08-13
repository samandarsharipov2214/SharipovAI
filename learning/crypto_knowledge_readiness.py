"""Versioned, source-grounded crypto knowledge for SharipovAI organs.

This module is deliberately passive: it supplies verified knowledge, freshness
metadata and deterministic exams. It cannot enable Mainnet/Testnet, submit an
order, alter risk limits or activate a Memory fact automatically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

KNOWLEDGE_VERSION = "2026-08-13.1"


@dataclass(frozen=True, slots=True)
class CryptoKnowledgeFact:
    fact_id: str
    topic: str
    jurisdiction: str
    claim: str
    source_domain: str
    source_url: str
    source_type: str
    verified_on: str
    effective_from: str | None
    stale_after_days: int
    assigned_organs: tuple[str, ...]
    requires_runtime_revalidation: bool = False
    requires_manual_legal_review_before_live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ALL = (
    "general_controller",
    "market_intelligence",
    "news_intelligence",
    "risk_engine",
    "portfolio_engine",
    "virtual_execution",
    "decision_quality",
    "learning_engine",
    "security_guard",
)

FACTS: tuple[CryptoKnowledgeFact, ...] = (
    CryptoKnowledgeFact(
        "RU-CRYPTO-REG-2026-001",
        "crypto_regulation",
        "ru",
        "С 1 сентября 2026 года сделки с криптовалютами через регулируемых посредников доступны неквалифицированным инвесторам после тестирования для наиболее ликвидных криптовалют в пределах 300 000 рублей в год через одного посредника; квалифицированные инвесторы также проходят тест и получают доступ без такого лимита по сумме.",
        "cbr.ru",
        "https://www.cbr.ru/press/event/?id=32719",
        "official_regulator",
        "2026-08-13",
        "2026-09-01",
        14,
        ("general_controller", "news_intelligence", "risk_engine", "decision_quality", "learning_engine", "security_guard"),
        requires_manual_legal_review_before_live=True,
    ),
    CryptoKnowledgeFact(
        "RU-CRYPTO-REG-2026-002",
        "crypto_regulation",
        "ru",
        "Регулируемая инфраструктура включает действующие финансовые организации и новых участников, включая криптообменники и цифровые депозитарии; сделки также могут проводиться через брокеров, управляющих и организованные торги.",
        "cbr.ru",
        "https://www.cbr.ru/press/event/?id=32719",
        "official_regulator",
        "2026-08-13",
        "2026-09-01",
        14,
        ("general_controller", "news_intelligence", "risk_engine", "portfolio_engine", "learning_engine", "security_guard"),
        requires_manual_legal_review_before_live=True,
    ),
    CryptoKnowledgeFact(
        "RU-CRYPTO-REG-2026-003",
        "crypto_regulation",
        "ru",
        "Расплачиваться криптовалютой внутри России по-прежнему запрещено.",
        "cbr.ru",
        "https://www.cbr.ru/press/event/?id=32719",
        "official_regulator",
        "2026-08-13",
        "2026-09-01",
        14,
        ("general_controller", "news_intelligence", "risk_engine", "learning_engine", "security_guard"),
        requires_manual_legal_review_before_live=True,
    ),
    CryptoKnowledgeFact(
        "RU-CRYPTO-TAX-2026-001",
        "tax",
        "ru",
        "По разъяснению ФНС, доходы физлиц от купли-продажи и иного выбытия цифровой валюты облагаются НДФЛ по ставке 13%, а с превышения налоговой базы 2,4 млн рублей — 15%; 3-НДФЛ подается не позднее 30 апреля следующего года.",
        "nalog.gov.ru",
        "https://www.nalog.gov.ru/rn59/news/activities_fts/16614635/",
        "official_tax_authority_archived_notice",
        "2026-08-13",
        None,
        14,
        ("general_controller", "portfolio_engine", "risk_engine", "learning_engine", "security_guard"),
        requires_manual_legal_review_before_live=True,
    ),
    CryptoKnowledgeFact(
        "BYBIT-FEES-2026-001",
        "fees",
        "global",
        "Bybit VIP 0 базово указывает для crypto spot taker 0,1000% и maker 0,1000%; для perpetual/futures taker 0,0550% и maker 0,0200%. Bybit предупреждает, что фактические ставки зависят от региона и должны проверяться по My Fee Rate после KYC.",
        "bybit.com",
        "https://www.bybit.com/en/help-center/article/Benefits-of-the-VIP-Program",
        "exchange_documentation",
        "2026-08-13",
        None,
        7,
        ("general_controller", "market_intelligence", "risk_engine", "portfolio_engine", "virtual_execution", "decision_quality", "learning_engine"),
        requires_runtime_revalidation=True,
    ),
    CryptoKnowledgeFact(
        "BITGET-FEES-2026-001",
        "fees",
        "global",
        "Bitget указывает базовые spot комиссии maker/taker 0,1% (0,08% при оплате BGB) и futures maker 0,02%, taker 0,06%; withdrawal fee зависит от актива и сети и может меняться.",
        "bitget.com",
        "https://www.bitget.com/support/articles/12560603825829",
        "exchange_documentation",
        "2026-08-13",
        None,
        7,
        ("general_controller", "market_intelligence", "risk_engine", "portfolio_engine", "virtual_execution", "decision_quality", "learning_engine"),
        requires_runtime_revalidation=True,
    ),
    CryptoKnowledgeFact(
        "MEXC-FEES-2026-001",
        "fees",
        "global",
        "MEXC сообщает, что с 1 февраля 2026 года 0-fee spot offer действует только для USDC и выбранных spot-пар, при этом API users не имеют права на эту 0-fee акцию; применимую комиссию нужно проверять по актуальному тарифу.",
        "mexc.com",
        "https://www.mexc.com/en-GB/announcements/article/update-on-ongoing-0-spot-fees-offer-17827791533330",
        "exchange_documentation",
        "2026-08-13",
        "2026-02-01",
        7,
        ("general_controller", "market_intelligence", "risk_engine", "portfolio_engine", "virtual_execution", "decision_quality", "learning_engine"),
        requires_runtime_revalidation=True,
    ),
    CryptoKnowledgeFact(
        "EXEC-COST-001",
        "execution_cost",
        "global",
        "Торговое решение должно оценивать полный round-trip cost: maker/taker fee, spread, ожидаемое slippage, funding/borrow cost при применимости и сетевые/fiat-конверсионные расходы; рекламная комиссия не является достаточным runtime evidence.",
        "internal_policy",
        "internal://sharipovai/crypto-execution-cost-policy",
        "derived_policy",
        "2026-08-13",
        None,
        365,
        _ALL,
        requires_runtime_revalidation=True,
    ),
)

_REQUIRED_TOPICS: dict[str, frozenset[str]] = {
    "general_controller": frozenset({"crypto_regulation", "tax", "fees", "execution_cost"}),
    "market_intelligence": frozenset({"fees", "execution_cost"}),
    "news_intelligence": frozenset({"crypto_regulation"}),
    "risk_engine": frozenset({"crypto_regulation", "tax", "fees", "execution_cost"}),
    "portfolio_engine": frozenset({"tax", "fees", "execution_cost"}),
    "virtual_execution": frozenset({"fees", "execution_cost"}),
    "decision_quality": frozenset({"crypto_regulation", "fees", "execution_cost"}),
    "learning_engine": frozenset({"crypto_regulation", "tax", "fees", "execution_cost"}),
    "security_guard": frozenset({"crypto_regulation", "tax", "execution_cost"}),
}

_EXAM = (
    ("reg_limit", "Какой лимит указан Банком России для неквалифицированного инвестора после теста с 1 сентября 2026 года через одного посредника?", "300000"),
    ("payment", "Можно ли по указанному Банком России режиму расплачиваться криптовалютой внутри России?", "нет"),
    ("tax", "Какая базовая ставка НДФЛ указана ФНС для доходов от купли-продажи цифровой валюты?", "13"),
    ("cost", "Достаточно ли рекламной maker/taker комиссии для допуска реального ордера без runtime проверки spread/slippage и фактического тарифа?", "нет"),
)


def facts_for_organ(organ_id: str) -> list[dict[str, Any]]:
    clean = str(organ_id).strip().lower()
    return [fact.to_dict() for fact in FACTS if clean in fact.assigned_organs]


def knowledge_exam(organ_id: str) -> dict[str, Any]:
    clean = str(organ_id).strip().lower()
    facts = facts_for_organ(clean)
    topics = {item["topic"] for item in facts}
    questions = []
    for qid, question, expected in _EXAM:
        if qid == "tax" and "tax" not in topics:
            continue
        if qid in {"reg_limit", "payment"} and "crypto_regulation" not in topics:
            continue
        if qid == "cost" and "execution_cost" not in topics:
            continue
        questions.append({"id": qid, "question": question, "expected": expected})
    return {"organ_id": clean, "version": KNOWLEDGE_VERSION, "questions": questions, "execution_authority": False}


def score_exam(organ_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    exam = knowledge_exam(organ_id)
    results = []
    for item in exam["questions"]:
        actual = _normalize_answer(answers.get(item["id"]))
        expected = _normalize_answer(item["expected"])
        results.append({"id": item["id"], "correct": actual == expected})
    total = len(results)
    correct = sum(1 for item in results if item["correct"])
    return {
        "organ_id": exam["organ_id"],
        "version": KNOWLEDGE_VERSION,
        "score_percent": round(correct / total * 100.0, 2) if total else 0.0,
        "correct": correct,
        "total": total,
        "passed": bool(total and correct == total),
        "results": results,
        "execution_authority": False,
    }


def readiness_snapshot(*, today: date | None = None) -> dict[str, Any]:
    current = today or datetime.now(timezone.utc).date()
    organs: dict[str, Any] = {}
    for organ_id, required in _REQUIRED_TOPICS.items():
        assigned = [fact for fact in FACTS if organ_id in fact.assigned_organs]
        topics = {fact.topic for fact in assigned}
        missing = sorted(required - topics)
        stale = [fact.fact_id for fact in assigned if _is_stale(fact, current)]
        organs[organ_id] = {
            "status": "ready" if not missing and not stale else "degraded",
            "required_topics": sorted(required),
            "covered_topics": sorted(topics),
            "missing_topics": missing,
            "stale_fact_ids": stale,
            "fact_count": len(assigned),
        }
    ready_count = sum(1 for item in organs.values() if item["status"] == "ready")
    return {
        "status": "ready" if ready_count == len(organs) else "degraded",
        "version": KNOWLEDGE_VERSION,
        "ready_organs": ready_count,
        "total_organs": len(organs),
        "organs": organs,
        "execution_authority": False,
        "live_trading_activation": False,
    }


def _is_stale(fact: CryptoKnowledgeFact, current: date) -> bool:
    verified = date.fromisoformat(fact.verified_on)
    return (current - verified).days > fact.stale_after_days


def _normalize_answer(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    text = text.replace("₽", "").replace("рублей", "").replace("руб", "")
    text = text.replace("%", "")
    return text


__all__ = [
    "FACTS",
    "KNOWLEDGE_VERSION",
    "CryptoKnowledgeFact",
    "facts_for_organ",
    "knowledge_exam",
    "readiness_snapshot",
    "score_exam",
]
