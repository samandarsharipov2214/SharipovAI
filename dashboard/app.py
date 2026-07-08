"""FastAPI application factory for the SharipovAI dashboard."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner

from .routes import router


def create_app(
    runner_factory: Callable[[], SharipovAIRunner] | None = None,
) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app = FastAPI(title="SharipovAI OS")
    app.state.runner_factory = runner_factory or SharipovAIRunner
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    app.include_router(router)

    @app.post("/api/chat/message")
    def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        """Process a chat message and return a grounded runner response."""

        message = str((payload or {}).get("message", "")).strip()
        try:
            output = app.state.runner_factory().run()
            run = {
                "decision": str(getattr(output, "decision", "NO_DECISION")),
                "confidence": float(getattr(output, "confidence", 0.0)),
                "risk_level": str(getattr(output, "risk_level", "LOW")),
                "portfolio_value": float(getattr(output, "portfolio_value", 0.0)),
                "paper_cash": float(getattr(output, "paper_cash", 0.0)),
                "paper_equity": float(getattr(output, "paper_equity", 0.0)),
                "paper_pnl": float(getattr(output, "paper_pnl", 0.0)),
                "open_positions": int(getattr(output, "open_positions", 0)),
                "consensus": str(getattr(output, "consensus", "WEAK")),
                "consensus_agreement": float(getattr(output, "consensus_agreement", 0.0)),
                "reason": str(getattr(output, "reason", "")),
                "report": str(getattr(output, "report", "")),
            }
        except Exception:
            run = {
                "decision": "NO_DECISION",
                "confidence": 0.0,
                "risk_level": "LOW",
                "portfolio_value": 0.0,
                "paper_cash": 0.0,
                "paper_equity": 0.0,
                "paper_pnl": 0.0,
                "open_positions": 0,
                "consensus": "WEAK",
                "consensus_agreement": 0.0,
                "reason": "Runner временно недоступен.",
                "report": "Runner временно недоступен.",
            }
        decision = str(run.get("decision", "NO_DECISION")).upper()
        confidence = float(run.get("confidence", 0.0) or 0.0)
        risk = str(run.get("risk_level", "LOW"))
        positions = int(run.get("open_positions", 0) or 0)
        reply = (
            f"Я вижу твоё сообщение: «{message}». "
            f"Анализ выполнен. Решение: {decision}. "
            f"Уверенность: {confidence:.1f}%. Риск: {risk}. "
        )
        if decision == "BUY" and positions > 0:
            reply += "Открыта только демо-позиция. Реальные деньги не используются."
        else:
            reply += "Реальная сделка не открыта. Система работает в безопасном демо-режиме."
        return {"reply": reply, "run": run}

    return app


app = create_app()
