"""Telegram command adapter for specialized News AI agents.

This wraps the webhook handler without rewriting the large telegram_bot module.
"""

from __future__ import annotations

import html
from typing import Any, Callable

from news_monitor.agent_network import agent_detail, network_status, run_agent

COMMAND_TO_AGENT = {
    "/politics": "politics_ai",
    "/sports": "sports_ai",
    "/crypto_news": "crypto_ai",
    "/weather_news": "weather_ai",
    "/security_news": "security_ai",
    "/world_news": "world_ai",
    "/finance_news": "finance_ai",
}


def install_telegram_news_agent_commands() -> dict[str, Any]:
    """Monkeypatch webhook module handler once with safe command interception."""

    from dashboard import telegram_webhook_api as webhook

    if getattr(webhook, "_news_agent_commands_installed", False):
        return {"status": "already_installed"}
    original: Callable[[dict[str, Any]], None] = webhook.handle_message

    def wrapped(message: dict[str, Any]) -> None:
        text = str(message.get("text") or "").strip()
        chat_id = (message.get("chat") or {}).get("id")
        command = text.split()[0].lower() if text.startswith("/") else ""
        if chat_id and command == "/news_agents":
            webhook.send_message(int(chat_id), news_agents_text(), webhook.main_keyboard())
            return
        agent_id = COMMAND_TO_AGENT.get(command)
        if chat_id and agent_id:
            run_agent(agent_id)
            webhook.send_message(int(chat_id), news_agent_text(agent_id), webhook.main_keyboard())
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
        f"Всего: <b>{payload.get('agent_count', len(agents))}</b>",
        f"Активны: <b>{payload.get('healthy_count', 0)}</b>",
        f"Требуют внимания: <b>{payload.get('attention_count', 0)}</b>",
        "",
    ]
    for agent in agents:
        icon = "✅" if agent.get("status") == "active" else "⚠️"
        age = agent.get("data_freshness_seconds")
        lines.append(
            f"{icon} <b>{html.escape(str(agent.get('name')))}</b> — "
            f"{html.escape(str(agent.get('status')))}, sources {agent.get('source_count', 0)}, "
            f"items {agent.get('item_count', 0)}, freshness {age} сек."
        )
    lines.extend(["", "Команды: /politics /sports /crypto_news /weather_news /security_news /world_news /finance_news"])
    return "\n".join(lines)


def news_agent_text(agent_id: str) -> str:
    detail = agent_detail(agent_id)
    agent = detail.get("agent", {})
    if not agent:
        return "⚠️ News AI не найден."
    errors = agent.get("errors", [])
    lines = [
        f"📰 <b>{html.escape(str(agent.get('name')))}</b>",
        "",
        f"Статус: <b>{html.escape(str(agent.get('status')))}</b>",
        f"Health: <b>{agent.get('health_score', 0)}%</b>",
        f"Источников: <b>{agent.get('source_count', 0)}</b>",
        f"Материалов: <b>{agent.get('item_count', 0)}</b>",
        f"Память: <b>{agent.get('memory_count', 0)}</b>",
        f"Freshness: <b>{agent.get('data_freshness_seconds')} сек.</b>",
        f"Событий отправлено: <b>{agent.get('events_emitted', 0)}</b>",
        "",
        f"Последнее действие: {html.escape(str(agent.get('last_action', '')))}",
        f"Маршруты: {html.escape(', '.join(agent.get('routes_to', [])))}",
    ]
    if errors:
        lines.append(f"Ошибки источников: <b>{len(errors)}</b>")
    return "\n".join(lines)
