"""Dashboard integration for the SharipovAI Bot Communication Network."""
from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from ai_chat_orchestrator import AGENTS, answer_chat, detect_agent
from learning.ai_learning_core import BOT_NAMES
from learning.bot_communication import BotCommunicationNetwork

CHAT_BOT_ALIASES = {
    "general_controller": "general_controller", "general controller": "general_controller",
    "market_agent": "market_agent", "market agent": "market_agent",
    "news_agent": "news_agent", "news agent": "news_agent",
    "risk_engine": "risk_engine", "risk engine": "risk_engine",
    "portfolio_engine": "portfolio_engine", "portfolio engine": "portfolio_engine",
    "paper_trading_bot": "paper_trading_bot", "paper trading bot": "paper_trading_bot",
    "confidence_engine": "confidence_engine", "confidence engine": "confidence_engine",
    "consensus_engine": "consensus_engine", "consensus engine": "consensus_engine",
    "stress_bot": "stress_bot", "stress bot": "stress_bot",
    "learning_engine": "learning_engine", "learning engine": "learning_engine",
    "security_guard": "security_guard", "security guard": "security_guard",
}


def install_bot_communication_api(app: FastAPI) -> None:
    if getattr(app.state, "bot_communication_api_installed", False):
        return
    app.state.bot_communication_api_installed = True

    def network() -> BotCommunicationNetwork:
        path = Path(os.getenv("BOT_COMMUNICATION_DB")) if os.getenv("BOT_COMMUNICATION_DB") else None
        return BotCommunicationNetwork(path)

    @app.get("/api/bot-network/health")
    def health_api() -> dict[str, Any]:
        health = network().health()
        health["unified_chat"] = True
        health["agents"] = [{"id": key, **value} for key, value in AGENTS.items()]
        return health

    @app.get("/api/bot-network/matrix")
    def matrix_api() -> dict[str, Any]:
        return network().communication_matrix()

    @app.post("/api/bot-network/messages")
    def send_message_api(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return network().send_message(
            sender=str(data.get("sender", "general_controller")),
            recipient=str(data.get("recipient", "learning_engine")),
            message_type=str(data.get("message_type", "question")),
            topic=str(data.get("topic", "general")),
            payload=data.get("payload", {}) if isinstance(data.get("payload", {}), dict) else {},
            thread_id=str(data.get("thread_id")) if data.get("thread_id") else None,
            priority=str(data.get("priority", "normal")),
        )

    @app.post("/api/bot-network/broadcast")
    def broadcast_api(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        recipients = data.get("recipients")
        return network().broadcast(
            sender=str(data.get("sender", "general_controller")),
            recipients=recipients if isinstance(recipients, list) else None,
            message_type=str(data.get("message_type", "status_update")),
            topic=str(data.get("topic", "general")),
            payload=data.get("payload", {}) if isinstance(data.get("payload", {}), dict) else {},
            priority=str(data.get("priority", "normal")),
        )

    @app.post("/api/bot-network/consensus")
    def consensus_api(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        participants = data.get("participants")
        return network().request_consensus(
            topic=str(data.get("topic", "general")),
            question=str(data.get("question", "Need consensus.")),
            participants=participants if isinstance(participants, list) else None,
        )

    @app.post("/api/bot-network/chat")
    def bot_chat_api(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        requested_bot = _chat_bot(str(data.get("bot", data.get("recipient", "general_controller"))))
        text = str(data.get("message", "")).strip()
        state = data.get("state", {}) if isinstance(data.get("state", {}), dict) else {}
        if not text:
            return {"status": "empty_message", "reply": "Напиши вопрос AI-боту."}

        # Prefixing guarantees the same agent routing in web, Mini App and Telegram.
        routed_text = f"{requested_bot}: {text}"
        answer = answer_chat(routed_text, state)
        return {
            "status": answer.get("status", "ok"),
            "bot": requested_bot,
            "reply": answer.get("reply", "Ответ не сформирован."),
            "source_ai": answer.get("source_ai", requested_bot),
            "intent": answer.get("intent", "agent_chat"),
            "data": answer.get("data", {}),
        }

    @app.get("/api/bot-network/inbox/{bot_name}")
    def inbox_api(bot_name: str, unread_only: bool = False) -> dict[str, Any]:
        bot = _chat_bot(bot_name)
        return {"status": "ok", "bot": bot, "messages": network().inbox(bot, unread_only=unread_only)}

    @app.get("/api/bot-network/outbox/{bot_name}")
    def outbox_api(bot_name: str) -> dict[str, Any]:
        bot = _chat_bot(bot_name)
        return {"status": "ok", "bot": bot, "messages": network().outbox(bot)}

    @app.get("/api/bot-network/threads/{thread_id}")
    def thread_api(thread_id: str) -> dict[str, Any]:
        return network().thread(thread_id)

    @app.get("/api/bot-network/agent/{bot_name}/timeline")
    def timeline_api(bot_name: str) -> dict[str, Any]:
        bot = _chat_bot(bot_name)
        answer = answer_chat(f"{bot} покажи журнал действий", {})
        return {"status": answer.get("status", "ok"), "bot": bot, "reply": answer.get("reply", ""), "messages": answer.get("data", {}).get("messages", [])}

    @app.post("/api/bot-network/agent/{bot_name}/self-check")
    def self_check_api(bot_name: str) -> dict[str, Any]:
        bot = _chat_bot(bot_name)
        return answer_chat(f"{bot} проведи тест адекватности и проверь себя", {})

    @app.post("/api/bot-network/agent/{bot_name}/pause")
    def pause_api(bot_name: str) -> dict[str, Any]:
        bot = _chat_bot(bot_name)
        return answer_chat(f"{bot} поставь paper действия на паузу", {})

    @app.post("/api/bot-network/agent/{bot_name}/learn")
    def learn_api(bot_name: str) -> dict[str, Any]:
        bot = _chat_bot(bot_name)
        return answer_chat(f"{bot} отправь последние ошибки в Learning Engine", {})

    @app.get("/bot-network", response_class=HTMLResponse)
    def bot_network_page() -> HTMLResponse:
        return HTMLResponse(_render_bot_network(network().health()))


def _chat_bot(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    alias_key = value.strip().lower().replace("-", " ").replace("_", " ")
    detected = detect_agent(value.lower())
    bot = detected or CHAT_BOT_ALIASES.get(key) or CHAT_BOT_ALIASES.get(alias_key) or key
    return bot if bot in BOT_NAMES or bot in AGENTS else "general_controller"


def _render_bot_network(health: dict[str, Any]) -> str:
    rows = "".join(_bot_row(bot, responsibility) for bot, responsibility in health.get("responsibilities", {}).items())
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Agent Control</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">AGENT CONTROL</span><h1>Связь и контроль AI-ботов</h1><p>Одинаковая логика чата для сайта, Mini App и Telegram: отдельные диалоги, журнал, self-check, pause и Learning.</p><p><a href="/">Главная</a> · <a href="/api/bot-network/health">JSON health</a> · <a href="/api/bot-network/matrix">JSON matrix</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Ботов</small><b>{health.get('bot_count', 0)}</b></div><div class="stat"><small>Messages</small><b>{health.get('message_count', 0)}</b></div><div class="stat"><small>Unread</small><b>{health.get('unread_count', 0)}</b></div><div class="stat"><small>Threads</small><b>{health.get('thread_count', 0)}</b></div></div></section><section class="card"><h2>Боты и роли</h2><table><tbody>{rows}</tbody></table></section></main></body></html>"""


def _bot_row(bot: str, responsibility: str) -> str:
    return f"<tr><td><b>{escape(bot)}</b></td><td>{escape(responsibility)}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td{padding:10px;border-bottom:1px solid #243044}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
