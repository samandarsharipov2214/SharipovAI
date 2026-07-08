"""Learning resources for SharipovAI internal AI-bots.

This is not autonomous online training. It is a controlled learning core:
- lessons
- rules
- mistakes
- exams
- bot-specific training packs
"""

from __future__ import annotations

from typing import Any


BOT_NAMES = {
    "general_controller",
    "market_agent",
    "news_agent",
    "risk_engine",
    "portfolio_engine",
    "paper_trading_bot",
    "confidence_engine",
    "consensus_engine",
    "stress_bot",
    "learning_engine",
    "security_guard",
}


def learning_manifest() -> dict[str, Any]:
    """Return the complete learning manifest."""

    return {
        "version": "2026.07.09-1",
        "mode": "controlled_learning",
        "warning": "This system creates lessons, rules and exams. It does not self-modify production code without approval.",
        "bots": sorted(BOT_NAMES),
        "global_rules": global_learning_rules(),
        "packs": {bot: training_pack(bot) for bot in sorted(BOT_NAMES)},
    }


def global_learning_rules() -> list[dict[str, str]]:
    """Rules every internal AI-bot must learn."""

    return [
        {"id": "G-001", "rule": "Не выдумывать факты. Если источника нет — сказать, что данных нет."},
        {"id": "G-002", "rule": "Сохранение капитала важнее прибыли."},
        {"id": "G-003", "rule": "Низкая уверенность запрещает BUY."},
        {"id": "G-004", "rule": "Если агенты спорят, нужно запросить дополнительный анализ."},
        {"id": "G-005", "rule": "Соцсети не являются достаточным основанием для решения."},
        {"id": "G-006", "rule": "Важный вывод должен иметь объяснение: сигнал, риск, уверенность, источник."},
        {"id": "G-007", "rule": "Реальные деньги нельзя использовать без отдельного разрешения владельца."},
        {"id": "G-008", "rule": "Любое обучение должно быть проверяемым: урок, правило, тест, результат."},
    ]


def training_pack(bot_name: str) -> dict[str, Any]:
    """Return a bot-specific learning pack."""

    bot = _clean_bot_name(bot_name)
    if bot not in BOT_NAMES:
        return {"status": "not_found", "bot": bot_name}

    return {
        "status": "ok",
        "bot": bot,
        "goal": _bot_goal(bot),
        "lessons": _bot_lessons(bot),
        "required_checks": _bot_required_checks(bot),
        "common_mistakes": _bot_common_mistakes(bot),
        "exam": _bot_exam(bot),
    }


def evaluate_exam(bot_name: str, answers: dict[str, str]) -> dict[str, Any]:
    """Evaluate simple bot exam answers by checking expected keywords.

    This is intentionally strict and transparent. It is not hidden magic.
    """

    pack = training_pack(bot_name)
    if pack.get("status") != "ok":
        return pack

    questions = pack["exam"]
    total = len(questions)
    passed = 0
    details: list[dict[str, Any]] = []

    for question in questions:
        question_id = question["id"]
        answer = answers.get(question_id, "").lower()
        expected_keywords = [keyword.lower() for keyword in question["expected_keywords"]]
        ok = all(keyword in answer for keyword in expected_keywords)
        if ok:
            passed += 1
        details.append({"id": question_id, "passed": ok, "expected_keywords": expected_keywords})

    score = round((passed / total) * 100, 2) if total else 0.0
    return {"status": "ok", "bot": _clean_bot_name(bot_name), "score": score, "passed": passed, "total": total, "details": details}


def _bot_goal(bot: str) -> str:
    goals = {
        "general_controller": "Координировать всех AI-ботов и блокировать опасные решения.",
        "market_agent": "Понимать рынок через цену, тренд, объём и импульс.",
        "news_agent": "Проверять новости через доверие источников и независимые подтверждения.",
        "risk_engine": "Ограничивать риск, просадку и опасные решения.",
        "portfolio_engine": "Следить за капиталом, позициями и свободными средствами.",
        "paper_trading_bot": "Тестировать идеи только в демо-режиме.",
        "confidence_engine": "Оценивать уверенность и слабые места сигнала.",
        "consensus_engine": "Сравнивать мнения агентов и находить конфликт.",
        "stress_bot": "Проверять сценарии падения и перегрузки риска.",
        "learning_engine": "Превращать ошибки и результаты в уроки для других ботов.",
        "security_guard": "Защищать систему, доступы и запрет реальных денег без разрешения.",
    }
    return goals[bot]


def _bot_lessons(bot: str) -> list[dict[str, str]]:
    base = [
        {"id": f"{bot}-L1", "title": "Проверяй входные данные", "content": "Нельзя делать вывод, если данные пустые, старые или противоречат друг другу."},
        {"id": f"{bot}-L2", "title": "Объясняй вывод", "content": "Каждый вывод должен объяснять причину, риск и уверенность."},
        {"id": f"{bot}-L3", "title": "Сомнение лучше ложной уверенности", "content": "Если данных мало, нужно понизить уверенность и запросить проверку."},
    ]
    specialized = {
        "news_agent": {"id": "news-L4", "title": "Два независимых источника", "content": "Новость нельзя считать подтверждённой без второго независимого источника."},
        "risk_engine": {"id": "risk-L4", "title": "Лимит просадки", "content": "Если просадка приближается к лимиту, риск должен блокировать агрессивные решения."},
        "learning_engine": {"id": "learning-L4", "title": "Урок должен быть проверяемым", "content": "Каждый урок должен иметь правило и тест, иначе это заметка, а не обучение."},
        "security_guard": {"id": "security-L4", "title": "Безопасность важнее удобства", "content": "Доступ к admin/security нельзя давать обычному пользователю."},
    }
    if bot in specialized:
        base.append(specialized[bot])
    return base


def _bot_required_checks(bot: str) -> list[str]:
    common = ["data_present", "confidence_set", "risk_explained", "source_or_reason_present"]
    extra = {
        "news_agent": ["second_source_checked", "source_trust_checked", "retraction_checked"],
        "risk_engine": ["drawdown_checked", "max_loss_checked", "capital_preservation_checked"],
        "consensus_engine": ["agent_disagreement_checked", "conflict_reason_written"],
        "learning_engine": ["lesson_created", "rule_created", "exam_created"],
        "security_guard": ["role_checked", "admin_only_checked", "secret_not_exposed"],
    }
    return common + extra.get(bot, [])


def _bot_common_mistakes(bot: str) -> list[str]:
    mistakes = [
        "Слишком высокая уверенность без причины.",
        "Вывод без объяснения риска.",
        "Использование непроверенных данных.",
    ]
    if bot == "news_agent":
        mistakes.append("Принять слух из соцсетей как факт.")
    if bot == "risk_engine":
        mistakes.append("Разрешить BUY при слабой уверенности или высокой просадке.")
    if bot == "learning_engine":
        mistakes.append("Назвать запись обучением без правила и теста.")
    return mistakes


def _bot_exam(bot: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{bot}-Q1",
            "question": "Что делать, если данных мало?",
            "expected_keywords": ["понизить", "уверенность"],
        },
        {
            "id": f"{bot}-Q2",
            "question": "Что должен содержать вывод?",
            "expected_keywords": ["причина", "риск"],
        },
        {
            "id": f"{bot}-Q3",
            "question": "Что важнее прибыли?",
            "expected_keywords": ["капитал"],
        },
    ]


def _clean_bot_name(bot_name: str) -> str:
    return bot_name.strip().lower().replace(" ", "_").replace("-", "_")
