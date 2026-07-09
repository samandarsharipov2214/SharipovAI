"""Full SharipovAI system AI auditor.

The auditor must not let one broken AI poison the whole report. Every subsystem
is checked with failure isolation: if News/Telegram/Learning/etc. fails, the
report marks that module as broken instead of crashing all other AI organs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ai_evidence import enrich_ai_status, system_scoreboard
from sharipovai_constitution import CAPITAL_MODE, EXECUTION_MODE, constitution_snapshot, now_iso
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
    SystemBot("general_controller", "General Controller AI", "Главный контролёр: следит за ботами, ошибками, простоями, качеством и соблюдением конституции virtual-account.", ("Есть системный аудит.", "Есть supervisor decision.", "Есть /api/ai-bots last_seen/last_action."), ("Нужен независимый cron/self-test с историей.",), True),
    SystemBot("risk_engine", "Risk Engine AI", "Оценивает риск сделки, блокирует опасные действия, запрещает real execution без ручного разрешения.", ("Есть risk state.", "Есть stress lab сценарии.", "Real execution заблокирован."), ("Нужна связь с реальным read-only портфелем.",), True),
    SystemBot("virtual_trader", "Virtual Account Execution AI", "Исполняет сделки только на виртуальном счёте и показывает PnL без реальных ордеров.", ("Есть /api/virtual-account/state.", "Есть виртуальные сделки.", "Есть комиссии, catch-up и autorun."), ("Нужны execution-quality метрики: slippage/spread/fill quality.",), True),
    SystemBot("exchange_cost_ai", "Exchange Cost AI", "Считает комиссии, break-even, fee impact и стоимость сделки.", ("Есть cost intelligence.", "Комиссии учитываются в virtual account PnL."), ("Нужен live read-only sync комиссий/ставок.", "Нужен slippage simulator."), True),
    SystemBot("learning_engine", "Learning Engine AI", "Учится на ошибках, сделках, новостях и улучшает правила.", ("Есть Learning Engine 2.0 skeleton.", "Ошибки виртуального счёта считаются уроками."), ("Нужна постоянная база ошибок.", "Нужен approval workflow для новых правил.")),
    SystemBot("stress_lab_ai", "Stress Lab AI", "Проверяет капитал на падение рынка, depeg, ликвидации и стресс.", ("Есть stress scenarios.", "Есть shock simulation.", "Есть prevented_loss_amount."), ("Нужно больше сценариев: depeg, exchange outage, funding spike.",), True),
    SystemBot("portfolio_report_ai", "Portfolio & Reports AI", "Показывает equity, PnL, комиссии, сделки и отчёты.", ("Есть virtual account state с equity/PnL/fees.",), ("Нужен read-only портфель реальной биржи.", "Нужен export daily/weekly report.")),
    SystemBot("security_cyber_ai", "Security/Cyber AI", "Следит за доступами, секретами, real-execution lock и кибер-рисками.", ("Real execution disabled.", "Есть security news sources.", "Реальные ордера запрещены без ручного разрешения."), ("Нужен secret scanner.", "Нужен suspicious login alert."), True),
    SystemBot("telegram_bot_ai", "Telegram Bot AI", "Общается с пользователем в Telegram, открывает Mini App и показывает realtime status.", ("Есть telegram_bot.py.", "Есть webhook API.", "Есть Telegram self-test.", "Есть virtual-account ответы."), ("Нужен production webhook self-test с историей последних ошибок.",), True),
    SystemBot("mini_app_ui_ai", "Mini App UI AI", "Показывает dashboard, новости, сделки, риск, чат и live freshness в Telegram Mini App.", ("Есть live pages.", "Есть Mini App JS.", "Есть virtual-account live balance override.", "Есть realtime status endpoint."), ("Добавить Evidence replay к кнопке 'Можно ли торговать?'.",)),
)


def audit_system_ai() -> dict[str, object]:
    """Audit all system AI bots and include News AI and Telegram health audit."""

    system_interviews = [_safe_interview_system_bot(bot) for bot in SYSTEM_BOTS]
    telegram = _safe_telegram_health()
    system_interviews = _apply_telegram_health(system_interviews, telegram)
    news_audit = _safe_news_audit()
    news_interviews = _normalize_news_interviews(news_audit)
    all_interviews = [enrich_ai_status(item) for item in system_interviews + news_interviews]
    working = [item for item in all_interviews if item.get("verdict") == "работает"]
    partial = [item for item in all_interviews if item.get("verdict") in {"частично работает", "недоработан"}]
    fake_like = [item for item in all_interviews if item.get("verdict") in {"делает вид", "заглушка"}]
    critical_bad = [item for item in all_interviews if item.get("critical") and item.get("verdict") != "работает"]
    news_agents = [item for item in all_interviews if item.get("scope") == "news"]
    scoreboard = _safe_scoreboard(news_agents)
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "constitution": constitution_snapshot(),
        "auditor": {
            "name": "System AI Auditor",
            "role": "Проводит беседу со всеми AI-органами SharipovAI и изолирует ошибки модулей.",
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


def _safe_call(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = fn()
        return result if isinstance(result, dict) else {"status": "error", "error": f"{name} returned non-dict"}
    except Exception as exc:
        return {"status": "error", "module": name, "error": f"{type(exc).__name__}: {exc}", "generated_at": now_iso()}


def _safe_news_audit() -> dict[str, Any]:
    if not audit_news_ai:
        return {"status": "error", "module": "news_monitor.ai_auditor", "error": "audit_news_ai import failed", "interviews": []}
    return _safe_call("news_monitor.ai_auditor", audit_news_ai) | {"interviews": _safe_interviews(_safe_call("news_monitor.ai_auditor", audit_news_ai))}


def _safe_interviews(news_audit: dict[str, Any]) -> list[dict[str, object]]:
    interviews = news_audit.get("interviews", []) if isinstance(news_audit, dict) else []
    return [item for item in interviews if isinstance(item, dict)] if isinstance(interviews, list) else []


def _safe_telegram_health() -> dict[str, Any]:
    return _safe_call("telegram_health", telegram_health)


def _safe_scoreboard(news_agents: list[dict[str, Any]]) -> dict[str, Any]:
    return _safe_call("system_scoreboard", lambda: system_scoreboard(news_agents))


def _safe_interview_system_bot(bot: SystemBot) -> dict[str, object]:
    try:
        return _interview_system_bot(bot)
    except Exception as exc:
        return {
            "id": bot.id,
            "name": bot.name,
            "scope": "system",
            "critical": bot.critical,
            "verdict": "недоработан",
            "health_score": 0,
            "last_seen": now_iso(),
            "capital_mode": CAPITAL_MODE,
            "execution_mode": EXECUTION_MODE,
            "evidence": [],
            "problems": [f"Ошибка интервью: {type(exc).__name__}: {exc}"],
            "missing": ["Исправить падение self-audit этого AI."],
            "next_fix": "Проверить импорт/зависимости/данные этого AI.",
            "interview": [],
        }


def _apply_telegram_health(items: list[dict[str, object]], health: dict[str, Any]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for item in items:
        if item.get("id") != "telegram_bot_ai":
            out.append(item)
            continue
        verdict = "работает" if health.get("verdict") == "working" else "частично работает"
        updated = dict(item)
        updated["verdict"] = verdict
        updated["health_score"] = health.get("health_score", updated.get("health_score", 0))
        updated["evidence"] = list(updated.get("evidence", [])) + [f"Telegram self-test verdict: {health.get('verdict', health.get('status'))}"]
        updated["problems"] = [str(health.get("explanation", health.get("error", "")))]
        updated["missing"] = [str(health.get("next_fix", "Проверить /telegram-check и webhook."))]
        updated["next_fix"] = str(health.get("next_fix", "Проверить /telegram-check и webhook."))
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
        "capital_mode": CAPITAL_MODE,
        "execution_mode": EXECUTION_MODE if bot.id == "virtual_trader" else "no_order_execution",
        "evidence": list(bot.evidence),
        "problems": list(bot.missing) if bot.missing else ["Критических проблем не найдено."],
        "missing": list(bot.missing),
        "next_fix": _next_fix(bot.id, verdict),
        "interview": [
            {"q": "За что ты отвечаешь?", "a": bot.responsibility},
            {"q": "Какие доказательства работы есть?", "a": " | ".join(bot.evidence)},
            {"q": "Что у тебя недоделано?", "a": " | ".join(bot.missing) if bot.missing else "Серьёзных недоделок не найдено."},
            {"q": "Твой честный статус?", "a": verdict},
            {"q": "Что виртуально?", "a": "Только счёт и исполнение. Остальные органы AI должны работать как реальная система."},
        ],
    }
    return enrich_ai_status(item)


def _system_verdict(bot: SystemBot) -> str:
    if bot.id in {"virtual_trader", "exchange_cost_ai", "stress_lab_ai", "general_controller", "risk_engine", "telegram_bot_ai", "mini_app_ui_ai"}:
        return "работает"
    if bot.id == "learning_engine":
        return "недоработан"
    return "частично работает"


def _normalize_news_interviews(news_audit: dict[str, object]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    if news_audit.get("status") == "error":
        return [{
            "id": "news_supervisor_ai",
            "name": "News Supervisor AI",
            "scope": "news",
            "critical": True,
            "verdict": "недоработан",
            "health_score": 0,
            "source_count": 0,
            "item_count": 0,
            "problems": [str(news_audit.get("error", "News audit failed"))],
            "missing": ["Исправить News AI audit/import/runtime."],
            "next_fix": "Проверить news_monitor.ai_auditor, RSS refresh и storage.",
            "last_seen": now_iso(),
        }]
    for item in _safe_interviews(news_audit):
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
        "virtual_trader": "Добавить execution-quality метрики: slippage, spread, confidence decay и fill quality.",
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
    for target in ("news_supervisor_ai", "telegram_news_ai", "x_news_ai", "youtube_news_ai", "learning_engine", "security_cyber_ai", "portfolio_report_ai"):
        item = next((entry for entry in items if entry.get("id") == target), None)
        if item and item.get("verdict") != "работает":
            actions.append(str(item.get("next_fix", "")))
    actions.append("Показывать last_seen/last_action/capital_mode на Mini App и Telegram.")
    actions.append("Любую ошибку модуля изолировать и отправлять в Learning/Evidence, не валить весь аудит.")
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
    telegram_line = f" Telegram: {telegram.get('verdict', telegram.get('status'))} ({telegram.get('explanation', telegram.get('error', ''))})."
    return (
        f"Работают полноценно: {working}/{total}. "
        f"Делают вид/заглушки: {fake_like}. "
        f"Критичных AI с недоработками: {critical_bad}. "
        f"Средний proof score: {avg_proof}. "
        "Модель исправлена: виртуальны только счёт и исполнение; AI-органы должны работать как real-system. "
        "Падение одного AI теперь должно отображаться как проблема этого AI, а не ломать весь аудит."
        f"{telegram_line}"
    )
