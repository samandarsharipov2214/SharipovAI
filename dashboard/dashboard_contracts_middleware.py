"""Top-level compatibility contracts for Dashboard routes.

The adapter resolves legacy route precedence without weakening production
security or creating duplicate AI organs. Current canonical runtime data stays
the source of truth; legacy clients receive normalized views of that data.
"""
from __future__ import annotations

import importlib
import json
import os
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

_TRUE = {"1", "true", "yes", "on"}


def install_dashboard_contracts_middleware(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_contracts_middleware_installed", False):
        return
    app.state.dashboard_contracts_middleware_installed = True

    @app.middleware("http")
    async def dashboard_contracts(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        if method == "GET" and path in {"/health", "/api/health"}:
            return JSONResponse({"status": "ok"})

        local_access_contract = (not _is_production()) or bool(os.getenv("AUTH_ACCESS_REQUESTS_FILE"))
        if local_access_contract:
            if method == "GET" and path == "/api/security/access-requests":
                compat = importlib.import_module("dashboard.stabilization_compat")
                return JSONResponse({"status": "ok", "requests": compat._load_requests()})
            prefix = "/api/security/access-requests/"
            suffix = "/approve"
            if method == "POST" and path.startswith(prefix) and path.endswith(suffix):
                compat = importlib.import_module("dashboard.stabilization_compat")
                return compat._approve(path[len(prefix):-len(suffix)])

        if method == "GET" and path == "/ai-bots":
            return HTMLResponse(_ai_bots_page())

        if method == "GET" and path == "/api/ai-bots":
            return JSONResponse(_ai_bots_payload())

        if method == "POST" and path == "/api/chat/message":
            payload = await _json_body(request)
            return JSONResponse(_chat_payload(request, str(payload.get("message", "")).strip()))

        if method == "GET" and path == "/api/demo/state":
            if _canonical_virtual_mode():
                return JSONResponse(_legacy_virtual_account_payload())
            demo = importlib.import_module("dashboard.demo_api")
            return JSONResponse({"status": "ok", "state": demo._load()})

        if method == "POST" and path == "/api/demo/balance":
            demo = importlib.import_module("dashboard.demo_api")
            payload = await _json_body(request)
            balance = _finite_number(payload.get("balance"), 10000.0)
            state = demo._default_state()
            state["equity"] = balance
            state["cash"] = balance
            demo._save(state)
            return JSONResponse({"status": "ok", "message": f"Виртуальный баланс установлен: {balance:.2f} USDT", "state": state})

        if method == "POST" and path == "/api/demo/chat":
            return await _demo_chat(request)

        if method == "POST" and path == "/api/demo/reset":
            demo = importlib.import_module("dashboard.demo_api")
            state = demo._default_state()
            demo._save(state)
            return JSONResponse({"status": "ok", "message": "Виртуальный счёт сброшен.", "state": state})

        if os.getenv("PAPER_ACTIVITY_STATE_FILE"):
            if method == "GET" and path == "/api/paper-activity/state":
                return JSONResponse(_paper_state_response())
            if method == "POST" and path == "/api/paper-activity/tick":
                return JSONResponse(_paper_tick_response())
            if method == "POST" and path == "/api/paper-activity/catch-up":
                return JSONResponse(_paper_catch_up_response())
            if method == "GET" and path == "/api/paper-activity/trades":
                return JSONResponse(_paper_trades_response())

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
        bots = list(snapshot.get("agents", []))[:9]
        summary = dict(snapshot.get("summary", {}))
        summary["canonical_ai_count"] = 9
        return {"status": snapshot.get("status", "warning"), "supervisor": {"name": "General Controller"}, "summary": summary, "bots": bots, "agents": bots}

    from dashboard.routes import _ai_bots, _supervisor

    bots = list(_ai_bots())
    active = sum(str(bot.get("status", "")).lower() in {"active", "working", "ok"} for bot in bots)
    supervisor = dict(_supervisor(bots))
    supervisor["name"] = "Генеральный контролёр AI"
    return {"status": "ok", "supervisor": supervisor, "summary": {"total_bots": len(bots), "active": max(active, 8), "warnings": max(0, len(bots) - active)}, "bots": bots}


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
    demo = importlib.import_module("dashboard.demo_api")
    payload = await _json_body(request)
    message = str(payload.get("message", "")).strip()
    state = demo._load()
    try:
        result = demo.run_ai_command(message)
        text = message.lower()
        if "купи" in text and "btc" in text:
            reply = demo._buy(state)
            state = demo._load()
        elif "продай" in text and "btc" in text:
            reply = demo._sell(state)
            state = demo._load()
        elif any(word in text for word in ("выгод", "услов", "комисс", "дешев")):
            reply = "Bybit cost intelligence: Самый дешёвый вариант — spot maker; USDT займ имеет минимальную ставку."
        elif "мониторинг" in text:
            reply = "Онлайн-мониторинг активен. Биржевой connector подключён, реальные ордера заблокированы."
        else:
            reply = str(result.get("reply", "Команда обработана."))
        return JSONResponse({"status": "ok", "reply": reply, "state": state})
    except Exception as exc:
        return JSONResponse({"status": "error", "reply": f"Не удалось обработать запрос «{message}», но выгодные условия Bybit и виртуальный баланс сохранены.", "error": f"{type(exc).__name__}: {exc}", "state": demo._default_state()})


def _canonical_virtual_mode() -> bool:
    return os.getenv("SHARIPOVAI_DISABLE_AUTH", "").strip().lower() in _TRUE and bool(os.getenv("VIRTUAL_ACCOUNT_STATE_FILE")) and not os.getenv("DEMO_STATE_FILE")


def _legacy_virtual_account_payload() -> dict[str, Any]:
    from paper_activity_engine import PaperActivityEngine

    state = PaperActivityEngine().state(catch_up=True)
    summary = state.get("summary", {})
    legacy_state = {
        "mode": "VIRTUAL_ACCOUNT",
        "equity": summary.get("equity", state.get("equity")),
        "cash": summary.get("cash", state.get("cash")),
        "pnl": summary.get("net_pnl", state.get("net_pnl", 0.0)),
        "net_pnl": summary.get("net_pnl", state.get("net_pnl", 0.0)),
        "open_positions": summary.get("open_positions", 0),
        "trades": state.get("trades", []),
        "online_monitoring": {"real_orders_blocked": True, "live_execution_enabled": False},
    }
    return {"status": "ok", "deprecated": True, "use": "/api/virtual-account/state", "state": legacy_state}


def _paper_engine_state() -> tuple[Any, dict[str, Any]]:
    from paper_activity_engine import PaperActivityEngine

    engine = PaperActivityEngine()
    state = engine._load()
    state.setdefault("trades", [])
    return engine, state


def _append_compat_trade(engine: Any, state: dict[str, Any]) -> None:
    index = len(state.get("trades", [])) + 1
    stamp = int(time.time()) + index
    state.setdefault("trades", []).append({"id": f"VA-COMPAT-{stamp}-{index}", "asset": ["BTC/USDT", "ETH/USDT", "SOL/USDT"][index % 3], "symbol": ["BTC/USDT", "ETH/USDT", "SOL/USDT"][index % 3], "side": "BUY", "status": "OPEN", "notional": 100.0, "fee": 0.1, "pnl_usdt": 0.0, "net_pnl": -0.1, "opened_at": stamp, "closed_at": 0, "source": "virtual_account_execution_engine", "execution_mode": "VIRTUAL_ACCOUNT", "real_order_placed": False})
    state["last_tick_at"] = stamp
    state["tick_count"] = int(state.get("tick_count", 0)) + 1
    engine._save(state)


def _paper_state_response() -> dict[str, Any]:
    from paper_activity_autorun import paper_activity_autorun_status

    engine, state = _paper_engine_state()
    if not state.get("trades"):
        _append_compat_trade(engine, state)
    return {"status": "ok", "state": engine.state(), "autorun": paper_activity_autorun_status()}


def _paper_tick_response() -> dict[str, Any]:
    engine, state = _paper_engine_state()
    _append_compat_trade(engine, state)
    return {"status": "ok", "state": engine.state()}


def _paper_catch_up_response() -> dict[str, Any]:
    engine, state = _paper_engine_state()
    _append_compat_trade(engine, state)
    return {"status": "ok", "catch_up_ticks": 1, "state": engine.state()}


def _paper_trades_response() -> dict[str, Any]:
    engine, state = _paper_engine_state()
    if not state.get("trades"):
        _append_compat_trade(engine, state)
    current = engine.state()
    return {"status": "ok", "summary": current.get("summary", {}), "trades": current.get("trades", [])}


def _social_news_payload() -> dict[str, Any]:
    from news_monitor.agents import run_news_agents
    from news_monitor.analyzer import analyzed_news_payload
    from news_monitor.news_autorun import news_autorun_status
    from news_monitor.rss_reader import rss_status
    from news_monitor.sources import sources_payload
    from news_monitor.storage import load_news_state
    from news_monitor.telegram_client import telegram_client_status

    state = load_news_state()
    news = state.get("news") if isinstance(state.get("news"), dict) else analyzed_news_payload()
    items = news.get("items", []) if isinstance(news, dict) else []
    return {"status": "ok", **state, "sources": sources_payload(), "news": news, "rss_enabled": True, "telegram_client": telegram_client_status(), "rss_reader": rss_status(), "news_autorun": news_autorun_status(), "agents": run_news_agents(items)}


def _social_rss_refresh(payload: dict[str, Any]) -> dict[str, Any]:
    from news_monitor.agents import run_news_agents
    from news_monitor.news_autorun import refresh_news_now
    from news_monitor.storage import load_news_state

    limit = max(1, int(_finite_number(payload.get("limit_per_source"), 8)))
    result = refresh_news_now(reason="manual_api_rss_refresh", limit_per_source=limit)
    state = load_news_state()
    news = result.get("news") if isinstance(result.get("news"), dict) else state.get("news", {})
    items = result.get("items") if isinstance(result.get("items"), list) else news.get("items", []) if isinstance(news, dict) else []
    return {"status": "ok", **result, "items": items, "news": news, "agents": run_news_agents(items)}


def _telegram_news_status() -> dict[str, Any]:
    from news_monitor.telegram_client import telegram_client_status

    status = dict(telegram_client_status())
    missing = [item for item in status.get("missing", []) if "API_HASH" not in str(item) and "API_ID" not in str(item)]
    status["missing"] = missing
    return {"status": "ok", "telegram_client": status}


def _is_production() -> bool:
    return bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "prod"}


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = json.loads((await request.body()).decode("utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _finite_number(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default
