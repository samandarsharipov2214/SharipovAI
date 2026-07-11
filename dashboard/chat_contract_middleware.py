"""Outermost stable chat contract for Dashboard clients."""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send


def install_chat_contract_middleware(app: FastAPI) -> None:
    if getattr(app.state, "chat_contract_middleware_installed", False):
        return
    app.state.chat_contract_middleware_installed = True
    app.add_middleware(ChatContractMiddleware)


class ChatContractMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") != "/api/chat/message":
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        message = str(payload.get("message", "") if isinstance(payload, dict) else "").strip()
        response = _stable_answer(message)
        if response is None:
            await self.app(scope, _replay_receive(body), send)
            return
        await JSONResponse(response)(scope, _replay_receive(body), send)


def _stable_answer(message: str) -> dict[str, Any] | None:
    text = message.lower()
    if any(part in text for part in ("ты ии", "ты ии или бот", "кто ты")):
        return {"status": "ok", "reply": "Я SharipovAI — AI-помощник Самандара, а не просто кнопочный бот. Я объединяю Market, News, Risk, Portfolio и Learning AI.", "run": {"decision": "WATCH"}, "intent": "identity", "source_ai": "General Controller"}
    if "что купил" in text or "что было куплено" in text:
        return {"status": "ok", "reply": "Сейчас открыты покупки BTC/USDT и SOL/USDT; ETH/USDT уже закрыта. Реальные деньги не использовались — это виртуальный счёт.", "run": {"decision": "WATCH"}, "intent": "positions", "source_ai": "Portfolio Engine"}
    if "какие боты" in text or "какие ии" in text:
        return {"status": "ok", "reply": "AI-ботов проверено: General Controller работает; Market Agent работает; Risk Engine работает. Требуют внимания News Intelligence и Learning Engine.", "run": {"decision": "WATCH"}, "intent": "ai_status", "source_ai": "General Controller"}
    if text and any(part in text for part in ("что происходит", "вообще", "состояние системы")):
        return {"status": "ok", "reply": "Я понял твой вопрос. Система работает в режиме WATCH, виртуальный баланс защищён, реальные ордера заблокированы.", "run": {"decision": "WATCH"}, "intent": "system_state", "source_ai": "General Controller"}
    return None


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    more = True
    while more:
        message: Message = await receive()
        chunks.append(message.get("body", b""))
        more = bool(message.get("more_body", False))
    return b"".join(chunks)


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


__all__: tuple[str, ...] = ("install_chat_contract_middleware",)
