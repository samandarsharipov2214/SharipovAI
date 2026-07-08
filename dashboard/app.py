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
    """Create the FastAPI dashboard application.

    Args:
        runner_factory: Optional factory used to create runner instances.

    Returns:
        Configured FastAPI application.
    """

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
            run = output.to_dict()
        except Exception:
            run = {
                "decision": "NO_DECISION",
                "confidence": 0.0,
                "risk_level": "LOW",
                "paper_cash": 0.0,
                "paper_equity": 0.0,
                "paper_pnl": 0.0,
                "open_positions": 0,
                "consensus": "WEAK",
                "consensus_agreement": 0.0,
                "reason": "Runner временно недоступен.",
            }
        decision = str(run.get("decision", "NO_DECISION"))
        confidence = float(run.get("confidence", 0.0) or 0.0)
        risk = str(run.get("risk_level", "LOW"))
        positions = int(run.get("open_positions", 0) or 0)
        reply = (
            f"Я получил твою команду: «{message}». "
            f"Запустил анализ. Решение: {decision}. "
            f"Уверенность: {confidence:.1f}%. Риск: {risk}. "
        )
        if decision.upper() == "BUY" and positions > 0:
            reply += "Открыта виртуальная позиция в Paper Trading. Реальные деньги не использованы."
        else:
            reply += "Виртуальная сделка не открыта, система остается в безопасном режиме."
        return {"reply": reply, "run": run}

    return app


app = create_app()
