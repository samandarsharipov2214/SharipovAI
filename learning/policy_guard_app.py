"""Policy Action Guard API.

Run with:
    python -m uvicorn learning.policy_guard_app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI

from .policy_action_guard import guard_action, guard_batch
from .policy_journal import PolicyJournal


app = FastAPI(title="SharipovAI Policy Action Guard")


def journal() -> PolicyJournal:
    return PolicyJournal(Path(os.getenv("POLICY_JOURNAL_FILE", "data/policy_journal.json")))


@app.post("/api/policy-guard/check")
def check_action(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    action = payload.get("action", {})
    if not isinstance(action, dict):
        return {"status": "invalid_action"}
    latest = payload.get("latest_advice")
    if not isinstance(latest, dict):
        latest = journal().snapshot().get("latest_advice")
    return guard_action(action, latest)


@app.post("/api/policy-guard/check-batch")
def check_batch(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        return {"status": "invalid_actions"}
    latest = payload.get("latest_advice")
    if not isinstance(latest, dict):
        latest = journal().snapshot().get("latest_advice")
    return guard_batch([action for action in actions if isinstance(action, dict)], latest)
