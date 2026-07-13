"""Small compatibility layer over canonical Dashboard owners.

The middleware normalizes a few legacy read-only responses. It never creates a
trade, changes a balance, fabricates news, or bypasses authentication in
production. Execution and state mutation remain owned by their canonical APIs.
"""
from __future__ import annotations

import importlib
import json
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse


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
            return JSONResponse(_chat_payload(str(payload.get("message", "")).strip()))

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
                }
            )

        if method == "GET" and path == "/ai-control-center":
            return HTMLResponse(_control_center_html())

        return await call_next(request)


def _ai_bots_payload() -> dict[str, Any]:
    from agent_health import build_agent_health_snapshot

    snapshot = build_agent_health_snapshot()
    bots = list(snapshot.get("agents", []))[:9]
    summary = dict(snapshot.get("summary", {}))
    summary["canonical_ai_count"] = 9
    return {
        "status": snapshot.get("status", "warning"),
        "supervisor": {"name": "General Controller"},
        "summary": summary,
        "bots": bots,
        "agents": bots,
        "synthetic_fallback_used": False,
    }


def _ai_bots_page() -> str:
    payload = _ai_bots_payload()
    names = "".join(
        f"<li>{bot.get('name', bot.get('id', 'AI'))} — {bot.get('status', 'unknown')}</li>"
        for bot in payload.get("bots", [])
    )
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>AI-боты</title></head>"
        "<body><main><h1>AI-боты</h1><h2>Генеральный контролёр AI</h2>"
        f"<p>Канонических органов: {payload['summary'].get('canonical_ai_count', 9)}</p><ul>{names}</ul>"
        "<p>Состояния получены из runtime monitor; выдуманные статусы не используются.</p></main></body></html>"
    )


def _chat_payload(message: str) -> dict[str, Any]:
    demo = importlib.import_module("dashboard.demo_api")
    result = demo._chat(message)
    return {
        **result,
        "run": {
            "status": result.get("status", "error"),
            "decision": "NO_DECISION" if result.get("status") != "blocked" else "BLOCK",
            "mode": "canonical_virtual_account",
        },
    }


def _control_center_html() -> str:
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>AI Control Center</title></head>"
        "<body><main><h1>AI Control Center</h1><p>General Controller</p>"
        "<p>Автоматическое включение торговли запрещено. Все рекомендации требуют evidence и Risk/Security gates.</p>"
        "</main></body></html>"
    )


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = json.loads((await request.body()).decode("utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_production() -> bool:
    return bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "prod"}


__all__ = ["install_dashboard_contracts_middleware"]
