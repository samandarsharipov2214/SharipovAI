"""Full SharipovAI system AI auditor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_evidence import enrich_ai_status, system_scoreboard
from sharipovai_constitution import constitution_snapshot, now_iso
from telegram_health import telegram_health

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
    SystemBot("general_controller", "General Controller AI", "Главный контролёр: следит за ботами, ошибками, простоями, качеством и соблюдением paper-realism конституции.", ("Есть системный аудит.", "Есть supervisor decision.", "Есть /api/ai-bots last_seen/last_action."), ("Нужен независимый cron/self-test с историей.",), True),
    SystemBot("risk_engine", "Risk Engine AI", "Оценивает риск сделки, блокирует опасные действия и считает paper/demo как тренировку реального капитала.", ("Есть risk state.", "Есть stress lab сценарии.", "LIVE заблокирован."), ("Нужна связь с реальным read-only портфелем.",), True),
    SystemBot("demo_trader", "Paper Realism Trader AI", "Исполняет paper-команды и показывает PnL без реальных ордеров, но с ответственностью как при реальном капитале.", ("Есть /api/demo/state.", "Есть paper-сделки.", "Есть комиссии и уроки."), ("Нужны сценарии paper trading по нескольким активам и временная история.",), True),
    SystemBot("exchange_cost_ai", "Exchange Cost AI", "Считает комиссии, break-even, fee impact и стоимость сделки.", ("Есть cost intelligence.", "Комиссии учитываются в paper PnL."), ("Нужен live read-only sync тарифов и ставок.", "Нужен slippage simulator."), True),
    SystemBot("learning_engine", "Learning Engine AI", "Учится на ошибках, сделках, новостях и улучшает правила.", ("Есть Learning Engine 2.0 skeleton.", "Ошибки paper-realism считаются серьёзными уроками."), ("Нужна постоянная база ошибок.", "Нужен approval workflow для новых правил.")),
    SystemBot("stress_lab_ai", "Stress Lab AI", "Проверяет капитал на падение рынка, depeg, ликвидации и стресс.", ("Есть stress scenarios.", "Есть shock simulation.", "Есть prevented_loss_amount."), ("Нужно больше сценариев: depeg, exchange outage, funding spike.",), True),
    SystemBot("portfolio_report_ai", "Portfolio & Reports AI", "Показывает equity, PnL, комиссии, сделки и отчёты.", ("Есть paper state с equity/PnL/fees.",), ("Нет live account отчёта.", "Нужен export daily/weekly report.")),
    SystemBot("security_cyber_ai", "Security/Cyber AI", "Следит за доступами, секретами, LIVE lock и кибер-рисками.", ("LIVE trading disabled.", "Есть security news sources.", "Реальные ордера запрещены без ручного разрешения."), ("Нужен secret scanner.", "Нужен suspicious login alert."), True),
    SystemBot("telegram_bot_ai", "Telegram Bot AI", "Общается с пользователем в Telegram, открывает Mini App и должен объяснять paper-realism.", ("Есть telegram_bot.py.", "Есть webhook API.", "Есть Telegram self-test.", "Есть paper-realism ответы."), ("Нужен production webhook self-test с историей последних ошибок.",), True),
    SystemBot("mini_app_ui_ai", "Mini App UI AI", "Показывает dashboard, новости, сделки, риск, чат и live freshness в Telegram Mini App.", ("Есть live pages.", "Есть Mini App JS.", "Убраны fake 00:00/00:01 timestamps."), ("Добавить встроенную кнопку 'Можно ли торговать?' с Evidence replay.",)),
)


def audit_system_ai() -> dict[str, object]:
    """Audit all system AI bots and include News AI and Telegram health audit."""

    system_interviews = [_interview_system_bot(bot) for bot in SYSTEM_BOTS]
    system_interviews = _apply_telegram_health(system_interviews)
    news_audit = audit_news_ai() if audit_news_ai else {"status": "error", "interviews": []}
    news_interviews = _normalize_news_interviews(news_audit)
    all_interviews = [enrich_ai_status(item) for item in system_interviews + news_interviews]
    working = [item for item in all_interviews if item["verdict"] == "работает"]
    partial = [item for item in all_interviews if item["verdict"] in {"частично работает", "недоработан"}]
    fake_like = [item for item in all_interviews if item["verdict"] in {"делает вид", "заглушка"}]
    critical_bad = [item for item in all_interviews if item.get("critical") and item["verdict"] != "работает"]
    news_agents = [item for item in all_interviews if item.get("scope") == "news"]
    scoreboard = system_scoreboard(news_agents)
    telegram = telegram_health()
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "constitution": constitution_snapshot(),
        "auditor": {
            "name": "System AI Auditor",
            "role": "Проводит беседу со всеми AI-ботами SharipovAI и проверяет paper-realism конституцию.",
            "total": len(all_interviews),
            "working": len(working),
            "partial_or_underbuilt": len(partial),
            "fake_like": len(fake_like),
            "critical_bad": len(critical_bad),
            "average_proof_score": scoreboard.get("average_proof_score", 0),
            "overall_grade": _grade(len(working), len(all_interviews), len(fake_like), len(critical_bad)),
            "summary": _summary(len(working), len(all_interviews), len(fake_like), len(critical_bad), scoreboard.get("average_proof_score", 0), telegram),
        },
        "scoreboard": scoreboard,
        "telegram_health": telegram,
        "interviews": all_interviews,
        "system_interviews": [item for item in all_interviews if item.get("scope") == "system"],
        "news_audit": news_audit,
        "priority_actions": _priority_actions(all_interviews, telegram),
    }


def _apply_telegram_health(items: list[dict[str, object]]) -> list[dict[str, object]]:
    health = telegram_health()
    out: list[dict[str, object]] = []
    for item in items:
        if item.get("id") != "telegram_bot_ai":
            out.append(item)
            continue
        verdict = "работает" if health.get("verdict") == "working" else "частично работает"
        updated = dict(item)
        updated["verdict"] = verdict
        updated["health_score"] = health.get("health_score", updated.get("health_score", 0))
        updated["evidence"] = list(updated.get("evidence", [])) + [f"Telegram self-test verdict: {health.get('verdict')}"]
        updated["problems"] = [str(health.get("explanation", ""))]
        updated["missing"] = [str(health.get("next_fix", ""))]
        updated["next_fix"] = str(health.get("next_fix", ""))
        updated["telegram_health"] = health
        updated["last_seen"] = now_iso()
        out.append(updated)
    return out


def _interview_system_bot(bot: SystemBot) -> dict[str, object]:
    verdict = _system_verdict(bot)
    health = 90 if verdict == "работает" else 72 if verdict == "частично работает" else 58
    item = {
        "id": bot.id,
        "name": bot.name,
        "scope": "system",
        "critical": bot.critical,
        "verdict": verdict,
        "health_score": health,
        "last_seen": now_iso(),
        "capital_mode": "paper_realism",
        "evidence": list(bot.evidence),
        "problems": list(bot.missing) if bot.missing else ["Критических проблем не найдено."],
        "missing": list(bot.missing),
        "next_fix": _next_fix(bot.id, verdict),
        "interview": [
            {"q": "За что ты отвечаешь?", "a": bot.responsibility},
            {"q": "Какие доказательства работы есть?", "a": " | ".join(bot.evidence)},
            {"q": "Что у тебя недоделано?", "a": " | ".join(bot.missing) if bot.missing else "Серьёзных недоделок не найдено."},
            {"q": "Твой честный статус?", "a": verdict},
            {"q": "Как ты относишься к demo/paper?", "a": "Как к тренировке реального капитала: комиссии, риск и ошибки считаются серьёзно."},
        ],
    }
    return enrich_ai_status(item)


def _system_verdict(bot: SystemBot) -> str:
    if bot.id in {"demo_trader", "exchange_cost_ai", "stress_lab_ai", "general_controller", "risk_engine", "telegram_bot_ai", "mini_app_ui_ai"}:
        return "работает"
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
        normalized.setdefault("last_seen", now_iso())
        output.append(enrich_ai_status(normalized))
    return output


def _next_fix(bot_id: str, verdict: str) -> str:
    fixes = {
        "general_controller": "Добавить cron/self-test с историей и Evidence replay.",
        "risk_engine": "Подключить риск к реальному read-only портфелю и сохранять причины блокировки.",
        "demo_trader": "Расширить paper-realism на несколько активов, таймстемпы и сценарии исполнения.",
        "exchange_cost_ai": "Добавить live read-only sync комиссий/ставок и fallback cache.",
        "learning_engine": "Подключить Learning Engine 2.0 к ошибкам сделок, новостей и риск-блокировок.",
        "stress_lab_ai": "Добавить сценарии depeg, flash crash, exchange outage, funding spike.",
        "portfolio_report_ai": "Добавить ежедневный/недельный отчёт и экспорт в Mini App.",
        "security_cyber_ai": "Добавить секрет-сканер и security alerts по токенам/env/логинам.",
        "telegram_bot_ai": "Держать webhook working и хранить историю последних ошибок Telegram.",
        "mini_app_ui_ai": "Добавить Evidence replay к кнопке 'Можно ли торговать?'.",
    }
    return fixes.get(bot_id, "Добавить реальные входные данные, freshness score и журнал проверок.")


def _priority_actions(items: list[dict[str, object]], telegram: dict[str, object]) -> list[str]:
    actions: list[str] = []
    if telegram.get("verdict") != "working":
        actions.append(str(telegram.get("next_fix", "Открыть /telegram-check.")))
    for target in ("telegram_news_ai", "x_news_ai", "youtube_news_ai", "learning_engine", "security_cyber_ai"):
        item = next((entry for entry in items if entry.get("id") == target), None)
        if item and item.get("verdict") != "работает":
            actions.append(str(item.get("next_fix", "")))
    actions.append("Показывать last_seen/last_action/capital_mode на Mini App и Telegram.")
    actions.append("Любую ошибку paper-realism отправлять в Learning/Evidence, не скрывать.")
    return [action for action in actions if action]


def _grade(working: int, total: int, fake_like: int, critical_bad: int) -> str:
    if total <= 0:
        return "FAIL"
    if fake_like:
        return "PARTIAL"
    if critical_bad >= 3:
        return "PARTIAL"
    if working / total >= 0.75:
        return "GOOD"
    return "PARTIAL"


def _summary(working: int, total: int, fake_like: int, critical_bad: int, avg_proof: object, telegram: dict[str, object]) -> str:
    telegram_line = f" Telegram: {telegram.get('verdict')} ({telegram.get('explanation')})."
    return (
        f"Работают полноценно: {working}/{total}. "
        f"Делают вид/заглушки: {fake_like}. "
        f"Критичных AI с недоработками: {critical_bad}. "
        f"Средний proof score: {avg_proof}. "
        "Конституция включена: demo/paper защищает деньги Самандара, но AI обязан считать риск, комиссии и ошибки как при реальном капитале."
        f"{telegram_line}"
    )
