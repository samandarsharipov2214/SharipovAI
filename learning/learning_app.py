"""SharipovAI learning API entrypoint.

Run with:
    python -m uvicorn learning.learning_app:app --reload
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from .ai_learning_core import evaluate_exam, learning_manifest, training_pack


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
