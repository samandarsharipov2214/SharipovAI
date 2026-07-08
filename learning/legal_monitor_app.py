"""SharipovAI legal and regulatory monitor API.

Run with:
    python -m uvicorn learning.legal_monitor_app:app --reload
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from .legal_regulatory_monitor import evaluate_legal_change, legal_alert_summary, legal_monitor_plan, legal_monitor_policy


app = FastAPI(title="SharipovAI Legal Monitor")


@app.get("/api/legal/policy")
def legal_policy() -> dict[str, Any]:
    return {"status": "ok", "policy": legal_monitor_policy()}


@app.get("/api/legal/plan")
def legal_plan(region: str = "global") -> dict[str, Any]:
    return legal_monitor_plan(region)


@app.post("/api/legal/evaluate")
def legal_evaluate(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return evaluate_legal_change(payload)


@app.post("/api/legal/alerts")
def legal_alerts(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    changes = payload.get("changes", [])
    if not isinstance(changes, list):
        return {"status": "invalid_changes"}
    return legal_alert_summary([change for change in changes if isinstance(change, dict)])
