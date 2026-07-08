"""SharipovAI source discovery API.

Run with:
    python -m uvicorn learning.source_discovery_app:app --reload
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from .source_discovery import discovery_plan, rank_source_candidates, source_policy, validate_source_candidate


app = FastAPI(title="SharipovAI Source Discovery")


@app.get("/api/learning/discovery/policy")
def discovery_policy() -> dict[str, Any]:
    return {"status": "ok", "policy": source_policy()}


@app.get("/api/learning/discovery/plan")
def discovery_plan_all() -> dict[str, Any]:
    return discovery_plan()


@app.get("/api/learning/discovery/plan/{bot_name}")
def discovery_plan_for_bot(bot_name: str) -> dict[str, Any]:
    return discovery_plan(bot_name)


@app.post("/api/learning/discovery/validate")
def validate_candidate(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return validate_source_candidate(payload)


@app.post("/api/learning/discovery/rank")
def rank_candidates(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return {"status": "invalid_candidates"}
    return {"status": "ok", "candidates": rank_source_candidates([candidate for candidate in candidates if isinstance(candidate, dict)])}
