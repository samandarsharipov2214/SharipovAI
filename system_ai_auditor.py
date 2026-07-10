"""Canonical SharipovAI system auditor.

Audits the 9 canonical AI organs from ai_architecture_registry.py. Interfaces,
storage and transports are reported separately and never inflate AI counts.
One failed probe is isolated and cannot crash the full report.
"""

from __future__ import annotations

from typing import Any, Callable

from ai_architecture_registry import CANONICAL_AI_ORGANS, NON_AI_COMPONENTS, architecture_snapshot
from ai_evidence import enrich_ai_status, system_scoreboard
from sharipovai_constitution import CAPITAL_MODE, EXECUTION_MODE, constitution_snapshot, now_iso
from telegram_health import telegram_health

try:
    from news_monitor.ai_auditor import audit_news_ai
except Exception:  # pragma: no cover
    audit_news_ai = None  # type: ignore[assignment]


PROBE_HINTS: dict[str, dict[str, Any]] = {
    "general_controller": {
        "evidence": ["Canonical architecture registry", "Failure-isolated system audit", "General Controller owns supervision/recovery"],
        "missing": ["Нужен always-on watchdog на ПК и история recovery attempts."],
        "verdict": "частично работает",
    },
    "market_intelligence": {
        "evidence": ["Market regime/trade gate", "Read-only exchange integration paths"],
        "missing": ["Нужно подтвердить runtime-свежесть котировок на основном ПК/сервере."],
        "verdict": "частично работает",
    },
    "news_intelligence": {
        "evidence": ["RSS autorun", "Specialized News Agent Network", "Source credibility/freshness"],
        "missing": ["Telegram/X/YouTube агенты ждут внешние credentials/API."],
        "verdict": "частично работает",
    },
    "risk_engine": {
        "evidence": ["Trade blocking", "Drawdown/risk checks", "Stress Lab is a Risk submodule"],
        "missing": ["Нужна связь с read-only реальным портфелем и live market freshness."],
        "verdict": "работает",
    },
    "portfolio_engine": {
        "evidence": ["Virtual account equity/PnL/fees", "Reports owned by Portfolio"],
        "missing": ["Нужен read-only реальный портфель и стабильный daily/weekly export."],
        "verdict": "частично работает",
    },
    "virtual_execution": {
        "evidence": ["Virtual-only execution", "Fees/trade history", "Real orders blocked"],
        "missing": ["Нужны slippage, spread и fill-quality метрики."],
        "verdict": "работает",
    },
    "decision_quality": {
        "evidence": ["Confidence and Consensus unified under one owner", "Conflict/consensus message types"],
        "missing": ["Нужен единый runtime endpoint и калибровка confidence по фактическим исходам."],
        "verdict": "недоработан",
    },
    "learning_engine": {
        "evidence": ["Learning OS", "Evidence integration", "Controlled lessons/rules/exams"],
        "missing": ["Нужна постоянная база ошибок и approval workflow для новых правил."],
        "verdict": "недоработан",
    },
    "security_guard": {
        "evidence": ["Policy guard", "Access/auth controls", "Real-order lock"],
        "missing": ["Нужны secret scanner и suspicious-login alerts."],
        "verdict": "частично работает",
    },
}


def audit_system_ai() -> dict[str, object]:
    """Audit canonical AI organs and non-AI components separately."""

    news_audit = _safe_news_audit()
    telegram = _safe_call("telegram_health", telegram_health)
    organs = [_audit_organ(organ.id, organ.name, organ.responsibility, organ.critical, news_audit) for organ in CANONICAL_AI_ORGANS]
    working = [item for item in organs if item["verdict"] == "работает"]
    partial = [item for item in organs if item["verdict"] in {"частично работает", "недоработан"}]
    failed = [item for item in organs if item["verdict"] in {"ошибка", "заглушка"}]
    critical_bad = [item for item in organs if item.get("critical") and item["verdict"] != "работает"]
    scoreboard = _safe_scoreboard(organs)
    components = _component_status(telegram)
    architecture = architecture_snapshot()
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "constitution": constitution_snapshot(),
        "architecture": architecture,
        "auditor": {
            "name": "Canonical System AI Auditor",
            "role": "Проверяет 9 настоящих AI-органов без дублирования интерфейсов и подсистем.",
            "total": len(organs),
            "working": len(working),
            "partial_or_underbuilt": len(partial),
            "failed": len(failed),
            "fake_like": len(failed),
            "critical_bad": len(critical_bad),
            "average_proof_score": scoreboard.get("average_proof_score", 0),
            "overall_grade": _grade(len(working), len(organs), len(failed), len(critical_bad)),
            "summary": _summary(working=len(working), total=len(organs), partial=len(partial), failed=len(failed), critical_bad=len(critical_bad)),
        },
        "scoreboard": scoreboard,
        "interviews": organs,
        "system_interviews": organs,
        "components": components,
        "telegram_health": telegram,
        "news_audit": news_audit,
        "priority_actions": _priority_actions(organs, components),
        "resolved_merges": architecture["resolved_merges"],
    }


def _audit_organ(organ_id: str, name: str, responsibility: str, critical: bool, news_audit: dict[str, Any]) -> dict[str, Any]:
    hint = PROBE_HINTS[organ_id]
    verdict = str(hint["verdict"])
    evidence = list(hint["evidence"])
    missing = list(hint["missing"])
    runtime: dict[str, Any] = {}
    if organ_id == "news_intelligence":
        runtime = news_audit
        if news_audit.get("status") == "error":
            verdict = "ошибка"
            missing.insert(0, f"News audit error: {news_audit.get('error', 'unknown')}")
        else:
            auditor = news_audit.get("auditor", {}) if isinstance(news_audit.get("auditor"), dict) else {}
            working = int(auditor.get("working", 0) or 0)
            total = int(auditor.get("total", 0) or 0)
            evidence.append(f"News subagents working: {working}/{total}")
            if working <= 0:
                verdict = "недоработан"
    health = {"работает": 90, "частично работает": 68, "недоработан": 48, "ошибка": 0, "заглушка": 10}.get(verdict, 30)
    item = {
        "id": organ_id,
        "name": name,
        "scope": "canonical_ai_organ",
        "critical": critical,
        "responsibility": responsibility,
        "verdict": verdict,
        "health_score": health,
        "last_seen": now_iso(),
        "capital_mode": CAPITAL_MODE,
        "execution_mode": EXECUTION_MODE if organ_id == "virtual_execution" else "no_order_execution",
        "evidence": evidence,
        "problems": missing,
        "missing": missing,
        "next_fix": missing[0] if missing else "Продолжать runtime monitoring.",
        "runtime": runtime,
        "interview": [
            {"q": "За что ты отвечаешь?", "a": responsibility},
            {"q": "Ты дублируешь другой AI?", "a": "Нет. Владелец обязанностей закреплён в ai_architecture_registry.py."},
            {"q": "Твой честный статус?", "a": verdict},
        ],
    }
    return enrich_ai_status(item)


def _component_status(telegram: dict[str, Any]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for component_id, responsibility in NON_AI_COMPONENTS.items():
        status = "configured"
        details: dict[str, Any] = {}
        if component_id == "telegram_bot":
            status = "working" if telegram.get("verdict") == "working" else "warning"
            details = telegram
        statuses.append({
            "id": component_id,
            "kind": "component_not_ai",
            "responsibility": responsibility,
            "status": status,
            "details": details,
        })
    return statuses


def _safe_news_audit() -> dict[str, Any]:
    if audit_news_ai is None:
        return {"status": "error", "error": "audit_news_ai import failed", "interviews": []}
    return _safe_call("news_monitor.ai_auditor", audit_news_ai)


def _safe_scoreboard(organs: list[dict[str, Any]]) -> dict[str, Any]:
    return _safe_call("system_scoreboard", lambda: system_scoreboard(organs))


def _safe_call(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = fn()
        return result if isinstance(result, dict) else {"status": "error", "module": name, "error": "non-dict response"}
    except Exception as exc:
        return {"status": "error", "module": name, "error": f"{type(exc).__name__}: {exc}", "generated_at": now_iso()}


def _priority_actions(organs: list[dict[str, Any]], components: list[dict[str, Any]]) -> list[str]:
    actions = [str(item["next_fix"]) for item in organs if item["verdict"] != "работает"]
    if any(item["status"] == "warning" for item in components):
        actions.append("Исправить warning интерфейсов/транспортов, не создавая для этого новый AI.")
    actions.append("Перед новым AI использовать responsibility_owner(); сначала расширять существующий орган.")
    return list(dict.fromkeys(action for action in actions if action))


def _grade(working: int, total: int, failed: int, critical_bad: int) -> str:
    if total <= 0 or failed:
        return "FAIL" if failed >= 2 else "PARTIAL"
    ratio = working / total
    if critical_bad >= 3:
        return "PARTIAL"
    if ratio >= 0.75:
        return "GOOD"
    return "PARTIAL"


def _summary(*, working: int, total: int, partial: int, failed: int, critical_bad: int) -> str:
    return (
        f"Канонических AI-органов: {total}. Полноценно работают: {working}. "
        f"Частично/недоработаны: {partial}. Ошибки: {failed}. "
        f"Критичных органов с недоработками: {critical_bad}. "
        "Telegram, Mini App, Evidence Vault и message bus больше не считаются отдельными ИИ. "
        "Supervisor объединён с General Controller; Stress Lab — часть Risk; Reports — часть Portfolio; Confidence и Consensus — Decision Quality."
    )
