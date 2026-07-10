"""Canonical SharipovAI AI architecture registry.

This file is the single source of truth for what counts as an AI organ, what is
only a subsystem, and what is only an interface/storage component. It prevents
new agents from duplicating existing responsibilities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sharipovai_constitution import now_iso


@dataclass(frozen=True)
class AIOrgan:
    id: str
    name: str
    responsibility: str
    owns: tuple[str, ...]
    submodules: tuple[str, ...] = ()
    legacy_aliases: tuple[str, ...] = ()
    critical: bool = False


CANONICAL_AI_ORGANS: tuple[AIOrgan, ...] = (
    AIOrgan(
        "general_controller",
        "General Controller AI",
        "Координация всей системы, health supervision, self-test, recovery orchestration и маршрутизация задач.",
        ("coordination", "supervision", "health_monitoring", "recovery_orchestration", "task_routing"),
        ("system_ai_auditor", "runtime_supervisor", "mission_control"),
        ("supervisor_ai", "system_supervisor"),
        True,
    ),
    AIOrgan(
        "market_intelligence",
        "Market Intelligence AI",
        "Реальные котировки, тренд, ликвидность, волатильность и рыночный режим.",
        ("quotes", "trend", "liquidity", "volatility", "market_regime"),
        ("market_agent", "exchange_readonly_market_data"),
        ("market_agent",),
        True,
    ),
    AIOrgan(
        "news_intelligence",
        "News Intelligence AI",
        "Сбор, классификация, проверка достоверности и маршрутизация реальных новостей.",
        ("news_collection", "source_verification", "credibility", "freshness", "event_routing"),
        ("news_supervisor", "politics", "world", "economy", "finance", "crypto", "sports", "weather", "security", "technology", "health", "telegram", "x", "youtube"),
        ("news_agent", "news_supervisor_ai", "main_news_supervisor_ai"),
        True,
    ),
    AIOrgan(
        "risk_engine",
        "Risk Engine AI",
        "Лимиты риска, просадка, блокировки и стресс-сценарии.",
        ("risk_limits", "drawdown", "trade_blocking", "scenario_risk", "prevented_loss"),
        ("stress_lab", "stress_bot"),
        ("stress_lab_ai", "stress_bot"),
        True,
    ),
    AIOrgan(
        "portfolio_engine",
        "Portfolio & Reports AI",
        "Капитал, позиции, PnL, комиссии, отчёты и ребалансировка.",
        ("portfolio", "positions", "pnl", "fees", "reports", "rebalancing"),
        ("reporting", "daily_report", "weekly_report"),
        ("portfolio_report_ai", "reports_ai"),
        True,
    ),
    AIOrgan(
        "virtual_execution",
        "Virtual Account Execution AI",
        "Исполнение только на виртуальном счёте, учёт комиссий и качества исполнения.",
        ("virtual_orders", "fills", "execution_quality", "fees", "trade_history"),
        ("paper_activity_engine", "virtual_account"),
        ("virtual_trader", "paper_trading_bot", "demo_trader"),
        True,
    ),
    AIOrgan(
        "decision_quality",
        "Decision Quality AI",
        "Единая оценка уверенности, конфликтов агентов и итогового консенсуса.",
        ("confidence", "consensus", "conflict_detection", "decision_quality"),
        ("confidence_engine", "consensus_engine"),
        ("confidence_engine", "consensus_engine"),
        True,
    ),
    AIOrgan(
        "learning_engine",
        "Learning Engine AI",
        "Преобразование ошибок и результатов в проверяемые уроки, правила и тесты.",
        ("lessons", "mistakes", "rules", "exams", "improvement_proposals"),
        ("learning_os", "autonomous_learning_cycle"),
        (),
        True,
    ),
    AIOrgan(
        "security_guard",
        "Security Guard AI",
        "Доступы, секреты, policy-ограничения, блокировка реальных ордеров и security alerts.",
        ("access_control", "secret_safety", "policy_guard", "real_order_lock", "security_alerts"),
        ("security_cyber", "policy_guard"),
        ("security_cyber_ai",),
        True,
    ),
)

NON_AI_COMPONENTS: dict[str, str] = {
    "telegram_bot": "Пользовательский интерфейс/транспорт, а не отдельный интеллект.",
    "mini_app_ui": "Интерфейс отображения, а не отдельный интеллект.",
    "evidence_vault": "Хранилище доказательств и решений, а не отдельный интеллект.",
    "bot_communication_network": "Транспорт сообщений между AI-органами.",
    "realtime_status": "Мониторинг и представление runtime-состояния.",
    "system_ai_auditor": "Диагностическая функция General Controller AI.",
}


def architecture_snapshot() -> dict[str, Any]:
    organs = [asdict(item) for item in CANONICAL_AI_ORGANS]
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "canonical_ai_count": len(organs),
        "organs": organs,
        "non_ai_components": NON_AI_COMPONENTS,
        "overlap_policy": {
            "rule": "Перед созданием нового AI сначала искать владельца обязанности в owns/submodules/legacy_aliases.",
            "decision": ["extend_existing", "merge_as_submodule", "create_only_if_unique"],
        },
        "resolved_merges": [
            {"from": ["General Controller", "Supervisor"], "to": "general_controller"},
            {"from": ["Risk Engine", "Stress Lab"], "to": "risk_engine + stress_lab submodule"},
            {"from": ["Portfolio", "Reports"], "to": "portfolio_engine"},
            {"from": ["Confidence", "Consensus"], "to": "decision_quality"},
            {"from": ["News Supervisor", "specialized News agents"], "to": "news_intelligence hierarchy"},
        ],
    }


def canonical_id(identifier: str) -> str | None:
    clean = identifier.strip().lower()
    for organ in CANONICAL_AI_ORGANS:
        aliases = {organ.id, *(alias.lower() for alias in organ.legacy_aliases), *(module.lower() for module in organ.submodules)}
        if clean in aliases:
            return organ.id
    return None


def responsibility_owner(capability: str) -> dict[str, Any]:
    clean = capability.strip().lower().replace(" ", "_")
    matches: list[dict[str, str]] = []
    for organ in CANONICAL_AI_ORGANS:
        fields = {value.lower() for value in (*organ.owns, *organ.submodules, *organ.legacy_aliases)}
        if clean in fields or any(clean in value or value in clean for value in fields):
            matches.append({"id": organ.id, "name": organ.name})
    return {
        "status": "ok" if matches else "unowned",
        "capability": capability,
        "owners": matches,
        "recommendation": "extend_existing" if len(matches) == 1 else "merge_or_disambiguate" if len(matches) > 1 else "candidate_for_new_organ",
    }
