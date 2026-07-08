"""SharipovAI learning API entrypoint.

Run with:
    python -m uvicorn learning.learning_app:app --reload
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from .ai_learning_core import evaluate_exam, learning_manifest, training_pack
from .financial_knowledge_library import bot_curriculum, knowledge_manifest


app = FastAPI(title="SharipovAI Learning Core")


@app.get("/api/learning/manifest")
def manifest() -> dict[str, Any]:
    """Return all learning packs and global rules."""

    return {"status": "ok", "manifest": learning_manifest()}


@app.get("/api/learning/bots/{bot_name}")
def bot_training_pack(bot_name: str) -> dict[str, Any]:
    """Return learning pack for one AI-bot."""

    return training_pack(bot_name)


@app.post("/api/learning/bots/{bot_name}/exam")
def bot_exam(bot_name: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """Evaluate bot exam answers."""

    answers = payload.get("answers", {})
    if not isinstance(answers, dict):
        return {"status": "invalid_answers"}
    return evaluate_exam(bot_name, {str(key): str(value) for key, value in answers.items()})


@app.get("/api/learning/finance/manifest")
def finance_manifest() -> dict[str, Any]:
    """Return the financial knowledge manifest."""

    return knowledge_manifest()


@app.get("/api/learning/finance/bots/{bot_name}")
def finance_bot_curriculum(bot_name: str) -> dict[str, Any]:
    """Return finance curriculum for one AI-bot."""

    return bot_curriculum(bot_name)
