"""Telegram command adapter for specialized News AI agents.

This wraps the webhook handler without rewriting the large telegram_bot module.
"""

from __future__ import annotations

import html
from typing import Any, Callable

from news_monitor.agent_bridge import bridge_events
from news_monitor.agent_network import agent_detail, network_status, run_agent
from news_monitor.news_autorun import refresh_news_if_stale

COMMAND_TO_AGENT = {
    "/politics": "politics_ai",
    "/sports": "sports_ai",
    "/crypto_news": "crypto_ai",
    "/weather_news": "weather_ai",
    "/security_news": "security_ai",
    "/world_news": "world_ai",
    "/finance_news": "finance_ai",
    "/economy_news": "economy_ai",
    "/technology_news": "technology_ai",
    "/health_news": "health_ai",
}


def install_telegram_news_agent_commands() -> dict[str, Any]:
    """Monkeypatch webhook handler once with safe command interception."""

    from dashboard import telegram_webhook_api as webhook

    if getattr(webhook, "_news_agent_commands_installed", False):
        return {"status": "already_installed"}
    original: Callable[[dict[str, Any]], None] = webhook.handle_message

    def wrapped(message: dict[str, Any]) -> None:
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        token = text.split()[0].lower() if text.startswith("/") else ""
        command = token.split("@", 1)[0]
        if chat_id and command == "/news_agents":
            refresh_news_if_stale(reason="telegram_news_agents")
            webhook.send_message(int(chat_id), news_agents_text(), webhook.main_keyboard())
            return
        agent_id = COMMAND_TO_AGENT.get(command)
        if chat_id and agent_id:
            refresh_news_if_stale(reason=f"telegram_news_agent:{agent_id}")
            result = run_agent(agent_id)
            bridge_events()
            webhook.send_message(int(chat_id), news_agent_text(agent_id, run_status=result.get("status")), webhook.main_keyboard())
            return
        original(message)

    webhook.handle_message = wrapped
    webhook._news_agent_commands_installed = True
    return {"status": "installed", "commands": ["/news_agents", *COMMAND_TO_AGENT.keys()]}


def news_agents_text() -> str:
    payload = network_status(run_due=True)
    agents = payload.get("agents", [])
    lines = [
        "🧠 <b>Специализированные News AI</b>",
        "",
        f"Сеть: <b>{html.escape(str(payload.get('status')))}</b>",
        f"Поток: <b>{'работает' if payload.get('thread_alive') else 'не работает'}</b>",
        f"Всего: <b>{payload.get('agent_count', len(agents))}</b>",
        f"Активны: <b>{payload.get('healthy_count', 0)}</b>",
        f"Требуют внимания: <b>{payload.get('attention_count', 0)}</b>",
        "",
    ]
    for agent in agents:
        icon = "✅" if agent.get("status") == "active" else "⏳" if agent.get("status") == "waiting_credentials" else "⚠️"
        lines.append(
            f"{icon} <b>{html.escape(str(agent.get('name')))}</b> — "
            f"{html.escape(str(agent.get('status')))}, источников {agent.get('source_count', 0)}, "
            f"материалов {agent.get('item_count', 0)}, freshness {_freshness(agent.get('data_freshness_seconds'))}."
        )
    lines.extend([
        "",
        "Команды: /politics /sports /crypto_news /weather_news /security_news",
        "/world_news /finance_news /economy_news /technology_news /health_news",
    ])
    return "\n".join(lines)


def news_agent_text(agent_id: str, *, run_status: object = None) -> str:
    detail = agent_detail(agent_id)
    agent = detail.get("agent", {})
    if not agent:
        return "⚠️ News AI не найден."
    errors = agent.get("errors", [])
    lines = [
        f"📰 <b>{html.escape(str(agent.get('name')))}</b>",
        "",
        f"Запуск: <b>{html.escape(str(run_status or 'ok'))}</b>",
        f"Статус: <b>{html.escape(str(agent.get('status')))}</b>",
        f"Health: <b>{agent.get('health_score', 0)}%</b>",
        f"Источников: <b>{agent.get('source_count', 0)}</b>",
        f"Материалов: <b>{agent.get('item_count', 0)}</b>",
        f"Память: <b>{agent.get('memory_count', 0)}</b>",
        f"Freshness: <b>{_freshness(agent.get('data_freshness_seconds'))}</b>",
        f"Новых событий: <b>{agent.get('events_emitted', 0)}</b>",
        "",
        f"Последнее действие: {html.escape(str(agent.get('last_action', '')))}",
        f"Маршруты: {html.escape(', '.join(str(route) for route in agent.get('routes_to', [])))}",
    ]
    if errors:
        lines.append(f"Ошибки источников: <b>{len(errors)}</b>")
    if agent.get("status") == "waiting_credentials":
        lines.append("Нужны credentials/API; агент честно не считается live.")
    return "\n".join(lines)


def _freshness(value: object) -> str:
    if value is None:
        return "нет успешного обновления"
    try:
        return f"{max(0, int(value))} сек."
    except (TypeError, ValueError):
        return "неизвестно"
