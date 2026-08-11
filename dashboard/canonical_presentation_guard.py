"""Outermost read/presentation guard for Web, Mini App and chat surfaces.

Legacy compatibility middleware remains importable for older tests and clients,
but it may not fabricate runtime state when the canonical SharipovAI package is
assembled. This guard performs no trading mutation.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_chat_orchestrator import answer_chat
from canonical_surface_state import load_canonical_paper_state


def install_canonical_presentation_guard(app: FastAPI) -> None:
    if getattr(app.state, "canonical_presentation_guard_installed", False):
        return
    app.state.canonical_presentation_guard_installed = True

    @app.middleware("http")
    async def canonical_presentation_guard(request: Request, call_next: Callable[[Request], Any]):
        path = request.url.path
        method = request.method.upper()

        if method == "GET" and path == "/api/ai-bots":
            from .realtime_status_api import canonical_agent_health

            return JSONResponse(canonical_agent_health(request.app))

        if method == "POST" and path in {"/api/chat/message", "/api/demo/chat"}:
            payload = await _json_payload(request)
            message = str(payload.get("message", "")).strip()
            state = load_canonical_paper_state()
            answer = answer_chat(message, state)
            return JSONResponse(
                {
                    "status": "ok" if answer.get("status") == "ok" else "warning",
                    "reply": str(answer.get("reply", "Ответ не сформирован.")),
                    "intent": answer.get("intent"),
                    "source_ai": answer.get("source_ai"),
                    "data": answer.get("data", {}),
                    "run": {
                        "decision": state.get("last_action") or "NO_CURRENT_DECISION",
                        "source_of_truth": state.get("source_of_truth"),
                        "state_status": state.get("status"),
                    },
                    "presentation_only": True,
                    "mutation_performed": False,
                }
            )

        canonical_loop = getattr(request.app.state, "autonomous_paper_loop", None)
        canonical_available = callable(getattr(canonical_loop, "snapshot", None))
        if canonical_available and method == "GET" and path == "/api/demo/state":
            state = load_canonical_paper_state()
            return JSONResponse(
                {
                    "status": state.get("status", "unavailable"),
                    "deprecated": True,
                    "source_of_truth": state.get("source_of_truth"),
                    "replacement": "/api/autonomous-paper/status",
                    "state": state,
                    "mutation_on_read": False,
                }
            )

        if canonical_available and method == "POST" and path in {"/api/demo/balance", "/api/demo/reset"}:
            return JSONResponse(
                {
                    "status": "deprecated",
                    "detail": "demo state mutation is disabled while canonical autonomous PAPER runtime is installed",
                    "replacement": "/api/autonomous-paper/status",
                    "mutation_performed": False,
                },
                status_code=410,
            )

        return await call_next(request)


async def _json_payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = ["install_canonical_presentation_guard"]
