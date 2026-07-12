"""Single source of truth for SharipovAI website, Mini App and Telegram.

Every public surface must expose the same sections, actions and terminology.
UI implementations may differ visually, but data, capabilities and state must not.
"""
from __future__ import annotations

from typing import Any

PRODUCT_SECTIONS: list[dict[str, Any]] = [
    {"id": "overview", "title": "Mission Control", "icon": "🏠", "web_target": "overview-section", "telegram_command": "start", "description": "Общее состояние системы, баланс, риск, решение и активность AI."},
    {"id": "copilot", "title": "AI Copilot", "icon": "💬", "web_target": "chat-section", "telegram_command": "ai", "description": "Общий чат с маршрутизацией к нужному AI-боту."},
    {"id": "bots", "title": "AI Agent Control", "icon": "🤖", "web_target": "bots-section", "telegram_command": "bots", "description": "Все AI-боты, роли, состояние, качество, ошибки и управление."},
    {"id": "risk", "title": "Risk Center", "icon": "⚠️", "web_target": "risk-section", "telegram_command": "risk", "description": "Профиль риска, лимиты, блокеры, Emergency Stop и самопроверка."},
    {"id": "trades", "title": "Сделки", "icon": "💼", "web_target": "trades-section", "telegram_command": "trades", "description": "Список сделок и переход в подробный отчёт по каждой сделке."},
    {"id": "learning", "title": "Learning Engine", "icon": "🧠", "web_target": "learning-section", "telegram_command": "learning", "description": "Ошибки, исправления, повторяющиеся проблемы, уроки и новые правила."},
    {"id": "reports", "title": "Reports", "icon": "📊", "web_target": "reports-section", "telegram_command": "reports", "description": "День, неделя, месяц, комиссии, просадка и вклад каждого AI."},
    {"id": "stress", "title": "Stress Lab", "icon": "🧪", "web_target": "stress-section", "telegram_command": "stress", "description": "Кризисные сценарии и реакция системы без реальных ордеров."},
    {"id": "timeline", "title": "Decision Timeline", "icon": "📒", "web_target": "timeline-section", "telegram_command": "timeline", "description": "Подтверждённый журнал действий по времени для системы и каждого бота."},
    {"id": "settings", "title": "Настройки", "icon": "⚙️", "web_target": "settings-section", "telegram_command": "settings", "description": "Единые настройки системы, доступные всем интерфейсам."},
]

TRADE_DETAIL_FIELDS = [
    "trade_id", "symbol", "side", "status", "opened_at", "closed_at", "duration",
    "entry_price", "exit_price", "quantity", "leverage", "gross_pnl", "fees",
    "net_pnl", "roi", "entry_reason", "exit_reason", "rejected_alternatives",
    "risk_snapshot", "agent_votes", "decision_timeline", "evidence", "learning_result",
]

AGENT_ACTIONS = [
    "chat", "report", "timeline", "self_check", "pause_paper", "send_to_learning",
    "show_errors", "show_current_task", "show_last_action", "show_evidence",
]

SYSTEM_RULES = {
    "single_database": True,
    "single_chat_orchestrator": True,
    "single_trade_state": True,
    "single_risk_state": True,
    "single_stop_ai_state": True,
    "single_bot_timeline": True,
    "no_fake_timeline": True,
    "no_decorative_health_scores_without_evidence": True,
    "live_execution_blocked_by_default": True,
}


def product_contract() -> dict[str, Any]:
    return {
        "version": "2.0-unified",
        "sections": PRODUCT_SECTIONS,
        "trade_detail_fields": TRADE_DETAIL_FIELDS,
        "agent_actions": AGENT_ACTIONS,
        "rules": SYSTEM_RULES,
        "surfaces": ["website", "mobile_web", "telegram_mini_app", "telegram_chat"],
    }
