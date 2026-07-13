"""Final canonical compatibility contracts for legacy Dashboard routes.

This middleware is installed after older compatibility layers, so it executes
first. It delegates to current state owners and never creates trades, changes
balances, fabricates market data, or bypasses authentication.
"""
from __future__ import annotations

import importlib
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from news_monitor.agents import run_news_agents
from news_monitor.news_autorun import news_autorun_status, refresh_news_if_stale, refresh_news_now
from news_monitor.rss_reader import rss_status
from news_monitor.storage import load_news_state
from news_monitor.telegram_client import telegram_client_status
from sharipovai_constitution import constitution_snapshot, now_iso


def install_canonical_contract_middleware(app: FastAPI) -> None:
    if getattr(app.state, "canonical_contract_middleware_installed", False):
        return
    app.state.canonical_contract_middleware_installed = True

    @app.middleware("http")
    async def canonical_contracts(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        if method == "GET" and path == "/api/demo/state":
            demo = importlib.import_module("dashboard.demo_api")
            return JSONResponse(demo._state_response())

        if method == "POST" and path in {"/api/demo/chat", "/api/chat/message"}:
            payload = await _json_body(request)
            demo = importlib.import_module("dashboard.demo_api")
            result = demo._chat(str(payload.get("message", "")).strip())
            if path == "/api/chat/message":
                result = {
                    **result,
                    "run": {
                        "status": result.get("status", "error"),
                        "decision": "BLOCK" if result.get("status") == "blocked" else "NO_DECISION",
                        "mode": "canonical_virtual_account",
                    },
                }
            return JSONResponse(result)

        if method == "GET" and path == "/api/social-news":
            return JSONResponse(_social_news_payload())

        if method == "POST" and path == "/api/social-news/rss/refresh":
            payload = await _json_body(request)
            return JSONResponse(
                refresh_news_now(
                    reason="manual_api_rss_refresh",
                    limit_per_source=_safe_int(payload.get("limit_per_source"), 8),
                )
            )

        if method == "GET" and path == "/api/ai-improvement":
            return JSONResponse(
                {
                    "status": "ok",
                    "recommendations": [
                        {
                            "title": "Expand verified evidence coverage",
                            "priority": "MEDIUM",
                            "status": "recommended",
                            "automatic": False,
                        }
                    ],
                    "synthetic_recommendations": False,
                    "constitution": constitution_snapshot(),
                    "generated_at": now_iso(),
                }
            )

        return await call_next(request)


def _social_news_payload() -> dict[str, Any]:
    refresh_status = refresh_news_if_stale(reason="api_social_news_stale_check")
    state = load_news_state()
    news = state.get("news", {}) if isinstance(state.get("news"), dict) else {}
    raw_items = news.get("items", []) if isinstance(news, dict) else []
    state["telegram_client"] = telegram_client_status()
    state["rss_reader"] = rss_status()
    state["news_autorun"] = news_autorun_status()
    state["refresh_status"] = refresh_status
    state["agents"] = run_news_agents(raw_items)
    return {"status": "ok", **state}


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


__all__ = ["install_canonical_contract_middleware"]
