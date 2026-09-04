"""Dashboard integration for the SharipovAI Bot Communication Network."""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from ai_chat_orchestrator import AGENTS, _action, answer_chat, detect_agent
from agent_intelligence import allow_intelligence_request
from learning.ai_learning_core import BOT_NAMES
from learning.bot_communication import BotCommunicationNetwork
from telegram_runtime_state import canonical_state_from_app

from .admin_guard import require_admin
from .auth_saas import ensure_same_origin, resolve_authenticated_principal
from .global_auth_guard import auth_disabled

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

DEFAULT_CONSENSUS_PARTICIPANTS = [
    "market_agent",
    "news_agent",
    "risk_engine",
    "portfolio_engine",
    "confidence_engine",
]


def _server_provenance_payload(data: dict[str, Any], actor: str) -> dict[str, Any]:
    """Return message payload with server-derived mutation provenance.

    Client-supplied ``requested_by`` is intentionally overwritten so audit identity
    cannot be forged through the Bot Network API.
    """

    payload = data.get("payload", {})
    safe_payload = dict(payload) if isinstance(payload, dict) else {}
    safe_payload["requested_by"] = actor
    return safe_payload


def _privileged_command_payload(*, text: str, action: str, actor: str) -> dict[str, Any]:
    return {
        "text": text,
        "source": "dashboard",
        "action": action,
        "user_message": True,
        "requested_by": actor,
    }


def _privileged_command_result(
    bus: BotCommunicationNetwork,
    *,
    bot: str,
    action: str,
    text: str,
    actor: str,
) -> dict[str, Any]:
    sender = "security_guard" if bot == "general_controller" else "general_controller"
    try:
        saved = bus.send_message(
            sender=sender,
            recipient=bot,
            message_type="command",
            topic="unified_chat",
            payload=_privileged_command_payload(text=text, action=action, actor=actor),
            priority="high" if action in {"pause", "self_check"} else "normal",
        )
    except Exception as exc:
        saved = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    meta = AGENTS.get(bot, AGENTS["general_controller"])
    if action == "self_check":
        reply = f"{meta['name']} принял команду самопроверки. Проверяются источник данных, last_seen, last_action, ошибки и соответствие роли. Итоговый verdict берётся из System AI Auditor, а не из самооценки бота."
    elif action == "pause":
        reply = f"{meta['name']}: запрос на паузу записан для paper/demo. LIVE уже заблокирован. Генеральный контролёр должен подтвердить смену состояния."
    else:
        reply = f"{meta['name']}: вопрос и последние ошибки отправлены в Learning Engine. Правило считается внедрённым только после evidence и повторного теста."
    return {
        "status": "ok" if saved.get("status") == "ok" else "persistence_error",
        "intent": "agent_chat",
        "source_ai": meta["name"],
        "reply": reply,
        "data": {
            "agent_id": bot,
            "role": meta["role"],
            "action": action,
            "message_bus": saved,
        },
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
    def send_message_api(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        ensure_same_origin(request)
        actor = require_admin(request)
        data = payload or {}
        return network().send_message(
            sender=str(data.get("sender", "general_controller")),
            recipient=str(data.get("recipient", "learning_engine")),
            message_type=str(data.get("message_type", "question")),
            topic=str(data.get("topic", "general")),
            payload=_server_provenance_payload(data, actor),
            thread_id=str(data.get("thread_id")) if data.get("thread_id") else None,
            priority=str(data.get("priority", "normal")),
        )

    @app.post("/api/bot-network/broadcast")
    def broadcast_api(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        ensure_same_origin(request)
        actor = require_admin(request)
        data = payload or {}
        recipients = data.get("recipients")
        return network().broadcast(
            sender=str(data.get("sender", "general_controller")),
            recipients=recipients if isinstance(recipients, list) else None,
            message_type=str(data.get("message_type", "status_update")),
            topic=str(data.get("topic", "general")),
            payload=_server_provenance_payload(data, actor),
            priority=str(data.get("priority", "normal")),
        )

    @app.post("/api/bot-network/consensus")
    def consensus_api(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        ensure_same_origin(request)
        actor = require_admin(request)
        data = payload or {}
        question = str(data.get("question", "")).strip()[:4_000]
        if not question:
            raise HTTPException(status_code=422, detail={"status": "question_required"})
        targets = _consensus_participants(data.get("participants"))
        if not targets:
            raise HTTPException(status_code=422, detail={"status": "valid_participants_required"})
        client_host = request.client.host if request.client else "unknown"
        external_key = str(request.headers.get("Idempotency-Key") or data.get("request_id") or secrets.token_hex(16))
        operation_id = hashlib.sha256(f"{actor}\0{external_key}".encode("utf-8")).hexdigest()[:32]
        bus = network()
        already_complete = bus.get_message_by_dedupe_key(
            f"consensus:{operation_id}:summary"
        ).get("status") == "ok"
        if not already_complete and not _reserve_intelligence_budget(
            f"consensus:{client_host}", len(targets) + 1
        ):
            raise HTTPException(status_code=429, detail={"status": "agent_chat_rate_limited"})
        return _execute_consensus(
            bus=bus,
            request=request,
            actor=actor,
            operation_id=operation_id,
            topic=str(data.get("topic", "general"))[:200] or "general",
            question=question,
            targets=targets,
        )

    @app.post("/api/bot-network/chat")
    def bot_chat_api(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        ensure_same_origin(request)
        data = payload or {}
        requested_bot = _chat_bot(str(data.get("bot", data.get("recipient", "general_controller"))))
        text = str(data.get("message", "")).strip()
        # Runtime evidence is server-owned.  A client-provided ``state`` object
        # must never become trusted model context or impersonate PAPER truth.
        state = canonical_state_from_app(request.app)
        if not isinstance(state, dict):
            state = {}
        if not text:
            return {"status": "empty_message", "reply": "Напиши вопрос AI-боту."}

        action = _action(text.lower())
        privileged_actor: str | None = None
        if action in {"pause", "self_check", "learn"}:
            privileged_actor = require_admin(request)

        bus = network()
        if privileged_actor is not None:
            generated = _privileged_command_result(
                bus,
                bot=requested_bot,
                action=action,
                text=text,
                actor=privileged_actor,
            )
            command = generated.get("data", {}).get("message_bus", {})
            return {
                "status": generated.get("status", "ok"),
                "bot": requested_bot,
                "reply": generated.get("reply", ""),
                "source_ai": generated.get("source_ai", requested_bot),
                "intent": generated.get("intent", "agent_chat"),
                "data": generated.get("data", {}),
                "message": command,
                "answer": {},
                "thread_id": command.get("thread_id"),
            }

        client_host = request.client.host if request.client else "unknown"
        if not allow_intelligence_request(client_host):
            raise HTTPException(status_code=429, detail={"status": "agent_chat_rate_limited"})

        sender = "security_guard" if requested_bot == "general_controller" else "general_controller"
        question = bus.send_message(
            sender=sender,
            recipient=requested_bot,
            message_type="question",
            topic="unified_chat",
            payload={"message": text, "channel": "dashboard"},
            priority="normal",
        )
        if question.get("status") != "ok":
            return {"status": "persistence_error", "message": question, "reply": "Вопрос не сохранён."}

        principal = resolve_authenticated_principal(request)
        if principal is None and auth_disabled():
            principal = "development"
        memory_user_id = _memory_user_id(principal)
        memory_service = getattr(request.app.state, "memory_service", None)
        memory_context: list[str] = []
        if memory_user_id and memory_service is not None:
            try:
                memory_context = memory_service.get_recent_dialog(
                    agent_id=requested_bot,
                    user_id=memory_user_id,
                )
            except Exception:
                memory_context = []

        routed_text = f"{requested_bot}: {text}"
        generated = answer_chat(
            routed_text,
            state,
            intelligent=True,
            persist_bus=False,
            memory_context=memory_context,
        )
        reply_text = str(generated.get("reply", "Ответ не сформирован."))
        answer = bus.reply(
            original_message_id=str(question["message_id"]),
            sender=requested_bot,
            message_type="answer",
            payload={
                "reply": reply_text,
                "source_ai": generated.get("source_ai", requested_bot),
                "intent": generated.get("intent", "agent_chat"),
                "data": generated.get("data", {}),
            },
        )
        if memory_user_id and memory_service is not None:
            _remember_chat_turn(
                memory_service,
                user_id=memory_user_id,
                agent_id=requested_bot,
                session_id=str(question.get("thread_id") or "unified_chat"),
                question=text,
                question_ref=str(question.get("message_id") or "question"),
                answer=reply_text,
                answer_ref=str(answer.get("message_id") or "") if answer.get("status") == "ok" else "",
            )
        status = "ok" if answer.get("status") == "ok" else "persistence_error"
        return {
            "status": status,
            "bot": requested_bot,
            "reply": reply_text,
            "source_ai": generated.get("source_ai", requested_bot),
            "intent": generated.get("intent", "agent_chat"),
            "data": generated.get("data", {}),
            "message": question,
            "answer": answer,
            "thread_id": question.get("thread_id"),
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
    def self_check_api(bot_name: str, request: Request) -> dict[str, Any]:
        ensure_same_origin(request)
        actor = require_admin(request)
        bot = _chat_bot(bot_name)
        return _privileged_command_result(
            network(),
            bot=bot,
            action="self_check",
            text=f"{bot} проведи тест адекватности и проверь себя",
            actor=actor,
        )

    @app.post("/api/bot-network/agent/{bot_name}/pause")
    def pause_api(bot_name: str, request: Request) -> dict[str, Any]:
        ensure_same_origin(request)
        actor = require_admin(request)
        bot = _chat_bot(bot_name)
        return _privileged_command_result(
            network(),
            bot=bot,
            action="pause",
            text=f"{bot} поставь paper действия на паузу",
            actor=actor,
        )

    @app.post("/api/bot-network/agent/{bot_name}/learn")
    def learn_api(bot_name: str, request: Request) -> dict[str, Any]:
        ensure_same_origin(request)
        actor = require_admin(request)
        bot = _chat_bot(bot_name)
        return _privileged_command_result(
            network(),
            bot=bot,
            action="learn",
            text=f"{bot} отправь последние ошибки в Learning Engine",
            actor=actor,
        )

    @app.get("/bot-network", response_class=HTMLResponse)
    def bot_network_page() -> HTMLResponse:
        return HTMLResponse(_render_bot_network(network().health()))


def _chat_bot(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    alias_key = value.strip().lower().replace("-", " ").replace("_", " ")
    detected = detect_agent(value.lower())
    bot = detected or CHAT_BOT_ALIASES.get(key) or CHAT_BOT_ALIASES.get(alias_key) or key
    return bot if bot in BOT_NAMES or bot in AGENTS else "general_controller"


def _consensus_participants(value: Any) -> list[str]:
    requested = value if isinstance(value, list) and value else DEFAULT_CONSENSUS_PARTICIPANTS
    targets: list[str] = []
    for item in requested[:5]:
        candidate = str(item).strip().lower().replace("-", "_").replace(" ", "_")
        if candidate in AGENTS and candidate != "consensus_engine" and candidate not in targets:
            targets.append(candidate)
    return targets


def _reserve_intelligence_budget(key: str, calls: int) -> bool:
    """Charge the existing limiter for every participant plus synthesis call."""

    return all(allow_intelligence_request(key) for _ in range(max(1, calls)))


def _execute_consensus(
    *,
    bus: BotCommunicationNetwork,
    request: Request,
    actor: str,
    operation_id: str,
    topic: str,
    question: str,
    targets: list[str],
) -> dict[str, Any]:
    """Execute only this owner-requested consensus; never consume legacy backlog."""

    thread_id = f"CNS-{operation_id.upper()}"
    requests: dict[str, dict[str, Any]] = {}
    for target in targets:
        saved = bus.send_message(
            sender="consensus_engine", recipient=target,
            message_type="consensus_request", topic=topic, priority="high",
            thread_id=thread_id, dedupe_key=f"consensus:{operation_id}:request:{target}",
            payload={
                "question": question,
                "required_response": "opinion,risk,confidence,source",
                "requested_by": actor,
                "operation_id": operation_id,
            },
        )
        if saved.get("status") != "ok":
            return {"status": "persistence_error", "operation_id": operation_id, "detail": saved}
        requests[target] = saved

    state = canonical_state_from_app(request.app)
    if not isinstance(state, dict):
        state = {}
    memory_service = getattr(request.app.state, "memory_service", None)
    principal = resolve_authenticated_principal(request)
    if principal is None and auth_disabled():
        principal = "development"
    memory_user_id = _memory_user_id(principal)

    pending: list[str] = []
    opinions: dict[str, str] = {}
    for target in targets:
        response_key = f"consensus:{operation_id}:response:{target}"
        existing = bus.get_message_by_dedupe_key(response_key)
        if existing.get("status") == "ok":
            payload = existing["message"].get("payload", {})
            opinions[target] = str(payload.get("reply", ""))
            # Recover the crash window after durable response persistence but
            # before terminalizing the corresponding request.
            bus.mark_read(str(requests[target]["message_id"]))
        else:
            pending.append(target)

    def ask(target: str) -> tuple[str, dict[str, Any]]:
        context: list[str] = []
        if memory_user_id and memory_service is not None:
            try:
                context = memory_service.get_recent_dialog(agent_id=target, user_id=memory_user_id)
            except Exception:
                context = []
        try:
            generated = answer_chat(
                f"{target}: {question}", state, intelligent=True,
                persist_bus=False, memory_context=context,
            )
        except Exception as exc:
            generated = {
                "status": "degraded", "reply": f"Ответ недоступен: {type(exc).__name__}",
                "source_ai": AGENTS[target]["name"], "data": {"intelligence": {"status": "unavailable"}},
            }
        return target, generated

    if pending:
        with ThreadPoolExecutor(max_workers=len(pending), thread_name_prefix="agent-consensus") as executor:
            generated_items = list(executor.map(ask, pending))
        for target, generated in generated_items:
            reply_text = str(generated.get("reply", "Ответ недоступен."))[:12_000]
            response = bus.send_message(
                sender=target, recipient="consensus_engine",
                message_type="consensus_response", topic=topic, priority="high",
                thread_id=thread_id, dedupe_key=f"consensus:{operation_id}:response:{target}",
                payload={
                    "reply": reply_text,
                    "source_ai": generated.get("source_ai", AGENTS[target]["name"]),
                    "intelligence": generated.get("data", {}).get("intelligence", {}),
                    "operation_id": operation_id,
                    "execution_authority": False,
                },
            )
            if response.get("status") == "ok":
                bus.mark_read(str(requests[target]["message_id"]))
                opinions[target] = reply_text

    ordered = [{"agent_id": target, "reply": opinions.get(target, "")} for target in targets]
    summary_key = f"consensus:{operation_id}:summary"
    existing_summary = bus.get_message_by_dedupe_key(summary_key)
    if existing_summary.get("status") == "ok":
        summary = str(existing_summary["message"].get("payload", {}).get("summary", ""))
    else:
        summary_context = [f"{item['agent_id']}: {item['reply']}" for item in ordered]
        try:
            synthesis = answer_chat(
                "consensus_engine: Сформируй итоговый консенсус, явно укажи конфликты, риск и неопределённость.",
                state, intelligent=True, persist_bus=False, memory_context=summary_context,
            )
            summary = str(synthesis.get("reply", ""))[:12_000]
        except Exception:
            summary = f"Получено {len(opinions)} из {len(targets)} ответов; автоматический синтез недоступен."
        bus.send_message(
            sender="consensus_engine", recipient="general_controller",
            message_type="answer", topic=topic, priority="high", thread_id=thread_id,
            dedupe_key=summary_key,
            payload={"summary": summary, "operation_id": operation_id, "execution_authority": False},
        )
    return {
        "status": "ok" if len(opinions) == len(targets) else "degraded",
        "operation_id": operation_id,
        "thread_id": thread_id,
        "participants": targets,
        "responses": ordered,
        "summary": summary,
        "execution_authority": False,
    }


def _memory_user_id(principal: str | None) -> str:
    if not principal:
        return ""
    digest = hashlib.sha256(principal.encode("utf-8")).hexdigest()
    return f"principal_{digest[:32]}"


def _remember_chat_turn(
    service: Any,
    *,
    user_id: str,
    agent_id: str,
    session_id: str,
    question: str,
    question_ref: str,
    answer: str,
    answer_ref: str,
) -> None:
    """Persist a redacted turn passively; chat remains available on memory faults."""

    created_at_ms = int(time.time() * 1_000)
    for offset, (role, message, source_ref) in enumerate((
        ("user", question, question_ref),
        ("assistant", answer, answer_ref),
    )):
        if not source_ref:
            continue
        try:
            service.record_dialog(
                team_id=service.settings.team_id,
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                message=message,
                source_ref=f"bot-network:{source_ref}",
                role=role,
                created_at_ms=created_at_ms + offset,
                metadata={"channel": "dashboard", "execution_authority": False},
            )
        except Exception:
            continue


def _render_bot_network(health: dict[str, Any]) -> str:
    rows = "".join(_bot_row(bot, responsibility) for bot, responsibility in health.get("responsibilities", {}).items())
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Agent Control</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">AGENT CONTROL</span><h1>Связь и контроль AI-ботов</h1><p>Одинаковая логика чата для сайта, Mini App и Telegram: отдельные диалоги, журнал, self-check, pause и Learning.</p><p><a href="/">Главная</a> · <a href="/api/bot-network/health">JSON health</a> · <a href="/api/bot-network/matrix">JSON matrix</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Ботов</small><b>{health.get('bot_count', 0)}</b></div><div class="stat"><small>Messages</small><b>{health.get('message_count', 0)}</b></div><div class="stat"><small>Unread</small><b>{health.get('unread_count', 0)}</b></div><div class="stat"><small>Threads</small><b>{health.get('thread_count', 0)}</b></div></div></section><section class="card"><h2>Боты и роли</h2><table><tbody>{rows}</tbody></table></section></main></body></html>"""


def _bot_row(bot: str, responsibility: str) -> str:
    return f"<tr><td><b>{escape(bot)}</b></td><td>{escape(responsibility)}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td{padding:10px;border-bottom:1px solid #243044}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
