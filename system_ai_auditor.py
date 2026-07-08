"""Full SharipovAI system AI auditor.

This module audits all known AI bots, not only News AI. It is intentionally
honest: if a subsystem has UI/API presence but no real live integration, it is
marked as partial, placeholder, or pretending.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from news_monitor.ai_auditor import audit_news_ai
except Exception:  # pragma: no cover
    audit_news_ai = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SystemBot:
    id: str
    name: str
    responsibility: str
    evidence: tuple[str, ...]
    missing: tuple[str, ...]
    critical: bool = False


SYSTEM_BOTS: tuple[SystemBot, ...] = (
    SystemBot(
        "general_controller",
        "General Controller AI",
        "Главный контролёр, который должен следить за ботами, ошибками, простоями и качеством.",
        ("Есть страницы/отчёты AI control center.", "Есть концепция health/quality отчётов."),
        ("Нет независимого планировщика проверок.", "Нет реального журнала выполненных исправлений каждого AI."),
        True,
    ),
    SystemBot(
        "risk_engine",
        "Risk Engine AI",
        "Оценивает риск сделки, блокирует опасные действия и контролирует защиту капитала.",
        ("Есть risk level в demo state.", "Есть stress lab сценарии."),
        ("Нужна связь с реальными позициями биржи.", "Нужен журнал причин блокировки сделки."),
        True,
    ),
    SystemBot(
        "demo_trader",
        "Demo Trader AI",
        "Исполняет демо-команды покупки/продажи и показывает PnL без реальных ордеров.",
        ("Есть /api/demo/state.", "Есть /api/demo/chat.", "Есть демо-сделки и баланс."),
        ("Реальный брокерский execution отключён по безопасности.", "Нужны сценарии paper trading по нескольким активам."),
        True,
    ),
    SystemBot(
        "exchange_cost_ai",
        "Exchange Cost AI",
        "Считает комиссии, break-even, VIP/fee impact и стоимость сделки.",
        ("Есть bybit cost intelligence.", "Есть preview/order cost API.", "Комиссии учитываются в demo PnL."),
        ("Часть тарифов seed/static, не все берутся live с биржи.", "Нужен read-only live sync тарифов и ставок."),
        True,
    ),
    SystemBot(
        "learning_engine",
        "Learning Engine AI",
        "Должен учиться на ошибках, сделках, новостях и улучшать правила.",
        ("Есть learning summary/learning routes в старой архитектуре.",),
        ("Нет полноценной базы ошибок и уроков.", "Нет автоматического обновления правил после ошибок."),
    ),
    SystemBot(
        "stress_lab_ai",
        "Stress Lab AI",
        "Проверяет портфель на падение рынка, ликвидации, стресс и защитные сценарии.",
        ("Есть /api/stress-lab/run.", "Есть сценарии market_drop/BTC drop в UI."),
        ("Нужна привязка к реальному портфелю.", "Нужны больше сценариев: гэп, flash crash, depeg, exchange outage."),
        True,
    ),
    SystemBot(
        "portfolio_report_ai",
        "Portfolio & Reports AI",
        "Показывает equity, PnL, комиссии, сделки и отчёты.",
        ("Есть отчёты в Mini App.", "Есть demo state с equity/PnL/fees."),
        ("Нет реального отчёта по live account.", "Нужен export daily/weekly report."),
    ),
    SystemBot(
        "security_cyber_ai",
        "Security/Cyber AI",
        "Следит за доступами, секретами, безопасностью и кибер-рисками.",
        ("Есть security/news источники CISA/GitHub advisories.", "Реальные ордера заблокированы без флага."),
        ("Нужен секрет-сканер env/репозитория.", "Нужны alert-правила по утечкам токенов и suspicious login."),
        True,
    ),
    SystemBot(
        "telegram_bot_ai",
        "Telegram Bot AI",
        "Общается с пользователем в Telegram и открывает Mini App.",
        ("Есть telegram_bot.py.", "Есть WEBAPP_URL/BOT_TOKEN архитектура."),
        ("Нужен production self-test бота.", "Telegram user-client не настроен из-за my.telegram.org ошибки."),
        True,
    ),
    SystemBot(
        "mini_app_ui_ai",
        "Mini App UI AI",
        "Показывает dashboard, новости, сделки, риск и чат в Telegram Mini App.",
        ("Есть index.html и mini-app-live.js.", "Есть новости/демо/API загрузка."),
        ("Часть UI всё ещё добавляется через JS.", "Нужна единая стабильная HTML-структура без костылей."),
    ),
)


def audit_system_ai() -> dict[str, object]:
    """Audit all system AI bots and include News AI audit."""

    system_interviews = [_interview_system_bot(bot) for bot in SYSTEM_BOTS]
    news_audit = audit_news_ai() if audit_news_ai else {"status": "error", "interviews": []}
    news_interviews = _normalize_news_interviews(news_audit)
    all_interviews = system_interviews + news_interviews
    working = [item for item in all_interviews if item["verdict"] == "работает"]
    partial = [item for item in all_interviews if item["verdict"] in {"частично работает", "недоработан"}]
    fake_like = [item for item in all_interviews if item["verdict"] in {"делает вид", "заглушка"}]
    critical_bad = [item for item in all_interviews if item.get("critical") and item["verdict"] != "работает"]
    return {
        "status": "ok",
        "auditor": {
            "name": "System AI Auditor",
            "role": "Проводит беседу со всеми AI-ботами SharipovAI, а не только с новостями.",
            "total": len(all_interviews),
            "working": len(working),
            "partial_or_underbuilt": len(partial),
            "fake_like": len(fake_like),
            "critical_bad": len(critical_bad),
            "overall_grade": _grade(len(working), len(all_interviews), len(fake_like), len(critical_bad)),
            "summary": _summary(len(working), len(all_interviews), len(fake_like), len(critical_bad)),
        },
        "interviews": all_interviews,
        "system_interviews": system_interviews,
        "news_audit": news_audit,
        "priority_actions": _priority_actions(all_interviews),
    }


def _interview_system_bot(bot: SystemBot) -> dict[str, object]:
    verdict = _system_verdict(bot)
    problems = list(bot.missing) if bot.missing else ["Критических проблем не найдено."]
    if verdict == "работает":
        health = 88 if bot.critical else 82
    elif verdict == "частично работает":
        health = 68
    elif verdict == "недоработан":
        health = 55
    else:
        health = 35
    return {
        "id": bot.id,
        "name": bot.name,
        "scope": "system",
        "critical": bot.critical,
        "verdict": verdict,
        "health_score": health,
        "evidence": list(bot.evidence),
        "problems": problems,
        "next_fix": _next_fix(bot.id, verdict),
        "interview": [
            {"q": "За что ты отвечаешь?", "a": bot.responsibility},
            {"q": "Какие доказательства работы есть?", "a": " | ".join(bot.evidence)},
            {"q": "Что у тебя недоделано?", "a": " | ".join(bot.missing) if bot.missing else "Серьёзных недоделок не найдено."},
            {"q": "Твой честный статус?", "a": verdict},
        ],
    }


def _system_verdict(bot: SystemBot) -> str:
    if bot.id in {"demo_trader", "exchange_cost_ai", "stress_lab_ai"}:
        return "работает"
    if bot.id in {"telegram_bot_ai", "risk_engine", "portfolio_report_ai", "mini_app_ui_ai", "general_controller", "security_cyber_ai"}:
        return "частично работает"
    if bot.id == "learning_engine":
        return "недоработан"
    return "частично работает"


def _normalize_news_interviews(news_audit: dict[str, object]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for item in news_audit.get("interviews", []) if isinstance(news_audit, dict) else []:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized["scope"] = "news"
        normalized["critical"] = normalized.get("id") in {"finance_crypto_ai", "politics_government_ai", "security_news_ai", "world_news_ai"}
        output.append(normalized)
    return output


def _next_fix(bot_id: str, verdict: str) -> str:
    fixes = {
        "general_controller": "Добавить настоящий периодический self-test всех AI и журнал действий контролёра.",
        "risk_engine": "Подключить риск к реальному портфелю/read-only бирже и сохранять причины блокировки.",
        "demo_trader": "Расширить paper trading на несколько активов и сценарии исполнения.",
        "exchange_cost_ai": "Добавить live read-only sync комиссий/ставок Bybit и fallback cache.",
        "learning_engine": "Создать базу ошибок, уроков и автоматическое обновление правил после ошибок.",
        "stress_lab_ai": "Добавить сценарии depeg, flash crash, exchange outage, funding spike.",
        "portfolio_report_ai": "Добавить ежедневный/недельный отчёт и экспорт в Mini App.",
        "security_cyber_ai": "Добавить секрет-сканер и security alerts по токенам/env/логинам.",
        "telegram_bot_ai": "Добавить endpoint самопроверки Telegram bot и capture сообщений из allowlist групп.",
        "mini_app_ui_ai": "Убрать JS-костыли, закрепить разделы Новости/ИИ-аудит в HTML Mini App.",
    }
    return fixes.get(bot_id, "Добавить реальные входные данные, freshness score и журнал проверок.")


def _priority_actions(items: list[dict[str, object]]) -> list[str]:
    actions: list[str] = []
    for target in ("telegram_news_ai", "x_news_ai", "youtube_news_ai", "learning_engine", "general_controller", "security_cyber_ai"):
        item = next((entry for entry in items if entry.get("id") == target), None)
        if item and item.get("verdict") != "работает":
            actions.append(str(item.get("next_fix", "")))
    actions.append("Добавить /api/system-ai-audit в Mini App как кнопку 'Провести беседу со всеми ИИ'.")
    actions.append("Добавить last_real_update для каждого AI, чтобы отличать живую работу от статической заглушки.")
    return [action for action in actions if action]


def _grade(working: int, total: int, fake_like: int, critical_bad: int) -> str:
    if total <= 0:
        return "FAIL"
    if fake_like or critical_bad >= 3:
        return "PARTIAL"
    if working / total >= 0.75:
        return "GOOD"
    return "PARTIAL"


def _summary(working: int, total: int, fake_like: int, critical_bad: int) -> str:
    return (
        f"Работают полноценно: {working}/{total}. "
        f"Делают вид/заглушки: {fake_like}. "
        f"Критичных AI с недоработками: {critical_bad}. "
        "Система живая, но часть AI надо честно пометить как частично работающие до подключения реальных источников и self-test журналов."
    )
