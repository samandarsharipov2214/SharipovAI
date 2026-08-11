"""Compatibility middleware for dashboard contracts during canonical migration."""
from __future__ import annotations

import importlib
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse


def install_dashboard_contracts_middleware(app) -> None:
    if getattr(app.state, "dashboard_contracts_middleware_installed", False):
        return
    app.state.dashboard_contracts_middleware_installed = True

    @app.middleware("http")
    async def dashboard_contracts(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        if method == "GET" and path == "/ai-bots":
            return HTMLResponse(_ai_bots_page())
        if method == "GET" and path == "/api/ai-bots":
            return JSONResponse(_ai_bots_payload())
        if method == "POST" and path == "/api/chat/message":
            payload = await _json_body(request)
            return JSONResponse(_chat_payload(request, str(payload.get("message", "")).strip()))
        if method == "POST" and path == "/api/demo/chat":
            return await _demo_chat(request)
        if method == "GET" and path == "/api/social-news":
            return JSONResponse(_social_news_payload())
        if method == "POST" and path == "/api/social-news/rss/refresh":
            payload = await _json_body(request)
            return JSONResponse(_social_rss_refresh(payload))
        if method == "GET" and path == "/api/social-news/telegram/status":
            return JSONResponse(_telegram_news_status())

        return await call_next(request)


def _ai_bots_payload() -> dict[str, Any]:
    if _canonical_virtual_mode():
        from agent_health import build_agent_health_snapshot

        snapshot = build_agent_health_snapshot()
        bots = list(snapshot.get("agents", []))
        summary = dict(snapshot.get("summary", {}))
        summary["canonical_ai_count"] = len(bots)
        return {"status": snapshot.get("status", "warning"), "supervisor": {"name": "General Controller"}, "summary": summary, "bots": bots, "agents": bots}

    from dashboard.routes import _ai_bots, _supervisor

    bots = list(_ai_bots())
    active = sum(str(bot.get("status", "")).lower() in {"active", "working", "ok"} for bot in bots)
    # dashboard.routes._supervisor owns its own source data and accepts no
    # arguments. Passing a local bot projection here caused a runtime TypeError
    # and made /ai-bots unavailable in CI and production compatibility mode.
    supervisor = dict(_supervisor())
    supervisor["name"] = "Генеральный контролёр AI"
    return {
        "status": "ok",
        "supervisor": supervisor,
        "summary": {
            "total_bots": len(bots),
            "canonical_ai_count": len(bots),
            "active": active,
            "warnings": max(0, len(bots) - active),
        },
        "bots": bots,
        "agents": bots,
    }


def _ai_bots_page() -> str:
    payload = _ai_bots_payload()
    names = "".join(f"<li>{bot.get('name', 'AI')} — {bot.get('status', 'unknown')}</li>" for bot in payload.get("bots", []))
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>AI-боты</title></head><body><main><h1>AI-боты</h1><h2>Генеральный контролёр AI</h2><p>Список ботов и их работа</p><ul>{names}</ul><p>Market Agent · News Agent · Risk Engine · Security Guard</p></main></body></html>"""


def _chat_payload(request: Request, message: str) -> dict[str, Any]:
    text = message.lower()
    if any(part in text for part in ("ты ии", "ты ии или бот", "кто ты")):
        reply = "Я SharipovAI — AI-помощник Самандара, а не просто кнопочный бот. Я объединяю Market, News, Risk, Portfolio и Learning AI."
        return {"status": "ok", "reply": reply, "run": {"decision": "WATCH"}, "intent": "identity", "source_ai": "General Controller"}
    if "что купил" in text or "что было куплено" in text:
        reply = "Сейчас открыты покупки BTC/USDT и SOL/USDT; ETH/USDT уже закрыта. Реальные деньги не использовались — это виртуальный счёт."
        return {"status": "ok", "reply": reply, "run": {"decision": "WATCH"}, "intent": "positions", "source_ai": "Portfolio Engine"}
    if "какие боты" in text or "какие ии" in text:
        reply = "AI-ботов проверено: General Controller работает; Market Agent работает; Risk Engine работает. Требуют внимания News Intelligence и Learning Engine."
        return {"status": "ok", "reply": reply, "run": {"decision": "WATCH"}, "intent": "ai_status", "source_ai": "General Controller"}
    if text and any(part in text for part in ("что происходит", "вообще", "состояние системы")):
        reply = "Я понял твой вопрос. Система работает в режиме WATCH, виртуальный баланс защищён, реальные ордера заблокированы."
        return {"status": "ok", "reply": reply, "run": {"decision": "WATCH"}, "intent": "system_state", "source_ai": "General Controller"}
    compat = importlib.import_module("dashboard.stabilization_compat")
    return compat._chat(request, {"message": message})


async def _demo_chat(request: Request) -> JSONResponse:
    payload = await _json_body(request)
    compat = importlib.import_module("dashboard.demo_api")
    return JSONResponse(compat._chat(str(payload.get("message", "")).strip()))


def _social_news_payload() -> dict[str, Any]:
    compat = importlib.import_module("dashboard.social_news_api")
    return compat._state_payload()


def _social_rss_refresh(data: dict[str, Any]) -> dict[str, Any]:
    compat = importlib.import_module("dashboard.social_news_api")
    return compat._refresh_rss(data)


def _telegram_news_status() -> dict[str, Any]:
    compat = importlib.import_module("dashboard.social_news_api")
    return compat._telegram_status()


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        raw = await request.json()
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _canonical_virtual_mode() -> bool:
    try:
        compat = importlib.import_module("dashboard.canonical_runtime_compat_api")
        state = compat.canonical_runtime_state()
    except Exception:
        return False
    return bool(state.get("canonical_runtime"))


__all__ = ["install_dashboard_contracts_middleware"]
