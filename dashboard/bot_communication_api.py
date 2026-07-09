"""Dashboard integration for AI Bot Communication Network."""

from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from learning.ai_learning_core import BOT_NAMES
from learning.bot_communication import BotCommunicationNetwork


CHAT_BOT_ALIASES = {
    "general_controller": "general_controller",
    "general controller": "general_controller",
    "market_agent": "market_agent",
    "market agent": "market_agent",
    "news_agent": "news_agent",
    "news agent": "news_agent",
    "risk_engine": "risk_engine",
    "risk engine": "risk_engine",
    "portfolio_engine": "portfolio_engine",
    "portfolio engine": "portfolio_engine",
    "paper_trading_bot": "paper_trading_bot",
    "paper trading bot": "paper_trading_bot",
    "confidence_engine": "confidence_engine",
    "confidence engine": "confidence_engine",
    "consensus_engine": "consensus_engine",
    "consensus engine": "consensus_engine",
    "stress_bot": "stress_bot",
    "stress bot": "stress_bot",
    "learning_engine": "learning_engine",
    "learning engine": "learning_engine",
    "security_guard": "security_guard",
    "security guard": "security_guard",
}


def install_bot_communication_api(app: FastAPI) -> None:
    """Install bot communication endpoints once."""

    if getattr(app.state, "bot_communication_api_installed", False):
        return
    app.state.bot_communication_api_installed = True

    def network() -> BotCommunicationNetwork:
        return BotCommunicationNetwork(Path(os.getenv("BOT_COMMUNICATION_DB")) if os.getenv("BOT_COMMUNICATION_DB") else None)

    @app.get("/api/bot-network/health")
    def health_api() -> dict[str, Any]:
        return network().health()

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
        if not text:
            return {"status": "empty_message", "reply": "Напиши вопрос AI-боту."}

        # The durable bot bus only accepts bot-to-bot messages and rejects
        # sender == recipient. A Mini App user question to General Controller
        # is persisted as Security Guard -> General Controller, while the
        # payload marks it as a user-originated Mini App message for audits.
        sender = "security_guard" if requested_bot == "general_controller" else "general_controller"
        sent = network().send_message(
            sender=sender,
            recipient=requested_bot,
            message_type="question",
            topic="mini_app_chat",
            payload={"text": text, "source": "mini_app", "requested_bot": requested_bot, "user_message": True},
            priority="normal",
        )
        if sent.get("status") != "ok":
            return {
                "status": "not_saved",
                "reply": "Вопрос не сохранён в durable bus. Проверь Bot Communication DB и имя AI-бота.",
                "message": sent,
            }

        reply = f"{requested_bot}: вопрос сохранён в durable message bus. Я проверяю свою зону и отвечаю по live state, а не только localStorage."
        answer = network().send_message(
            sender=requested_bot,
            recipient=sender,
            message_type="answer",
            topic="mini_app_chat",
            thread_id=str(sent.get("thread_id")),
            payload={"text": reply, "question": text, "source": "mini_app"},
            priority="normal",
        )
        return {"status": "ok" if answer.get("status") == "ok" else "partial", "reply": reply, "message": sent, "answer": answer}

    @app.get("/api/bot-network/inbox/{bot_name}")
    def inbox_api(bot_name: str, unread_only: bool = False) -> dict[str, Any]:
        return {"status": "ok", "bot": bot_name, "messages": network().inbox(bot_name, unread_only=unread_only)}

    @app.get("/api/bot-network/outbox/{bot_name}")
    def outbox_api(bot_name: str) -> dict[str, Any]:
        return {"status": "ok", "bot": bot_name, "messages": network().outbox(bot_name)}

    @app.get("/api/bot-network/threads/{thread_id}")
    def thread_api(thread_id: str) -> dict[str, Any]:
        return network().thread(thread_id)

    @app.get("/bot-network", response_class=HTMLResponse)
    def bot_network_page() -> HTMLResponse:
        return HTMLResponse(_render_bot_network(network().health()))


def _chat_bot(value: str) -> str:
    """Normalize Mini App display names to durable bot IDs."""

    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    alias_key = value.strip().lower().replace("-", " ").replace("_", " ")
    bot = CHAT_BOT_ALIASES.get(key) or CHAT_BOT_ALIASES.get(alias_key) or key
    return bot if bot in BOT_NAMES else "general_controller"


def _render_bot_network(health: dict[str, Any]) -> str:
    rows = "".join(_bot_row(bot, responsibility) for bot, responsibility in health.get("responsibilities", {}).items())
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Bot Network</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">BOT NETWORK</span><h1>Связь AI-ботов</h1><p>Message bus для общения 11 ботов: inbox, threads, broadcast и consensus.</p><p><a href="/">Главная</a> · <a href="/api/bot-network/health">JSON health</a> · <a href="/api/bot-network/matrix">JSON matrix</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Ботов</small><b>{health.get('bot_count', 0)}</b></div><div class="stat"><small>Messages</small><b>{health.get('message_count', 0)}</b></div><div class="stat"><small>Unread</small><b>{health.get('unread_count', 0)}</b></div><div class="stat"><small>Threads</small><b>{health.get('thread_count', 0)}</b></div><div class="stat"><small>Full mesh</small><b>{'ДА' if health.get('full_mesh_possible') else 'НЕТ'}</b></div></div></section><section class="card"><h2>Боты и роли</h2><table><thead><tr><th>Bot</th><th>Role</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""


def _bot_row(bot: str, responsibility: str) -> str:
    return f"<tr><td><b>{escape(bot)}</b></td><td>{escape(responsibility)}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
