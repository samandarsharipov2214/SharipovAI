"""Policy monitor dashboard and API.

Run with:
    python -m uvicorn learning.policy_dashboard_app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from .legal_source_watcher import LegalWatchStateStore
from .policy_journal import PolicyJournal
from .policy_ops import run_policy_ops


app = FastAPI(title="SharipovAI Policy Monitor")


def watch_store() -> LegalWatchStateStore:
    return LegalWatchStateStore(Path(os.getenv("LEGAL_WATCH_STATE_FILE", "data/legal_watch_state.json")))


def journal() -> PolicyJournal:
    return PolicyJournal(Path(os.getenv("POLICY_JOURNAL_FILE", "data/policy_journal.json")))


@app.get("/policy-monitor", response_class=HTMLResponse)
def policy_monitor_page() -> HTMLResponse:
    snap = journal().snapshot(limit=50)
    rows = "".join(_row(alert) for alert in snap["alerts"]) or "<tr><td colspan='6'>Пока нет alert</td></tr>"
    latest = snap.get("latest_advice") or {}
    return HTMLResponse(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Policy Monitor</title><style>body{{background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif;margin:0}}main{{max-width:1100px;margin:0 auto;padding:32px}}.card{{background:#071426;border:1px solid #26364f;border-radius:24px;padding:22px;margin:16px 0}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #26364f;padding:10px;text-align:left}}.critical{{color:#ff6b75;font-weight:800}}.high{{color:#ffb86b;font-weight:800}}.caution{{color:#f8e16c;font-weight:800}}a{{color:#7dd3fc}}</style></head><body><main><h1>Legal / Policy Monitor</h1><section class="card"><h2>Совет главному ИИ</h2><p><b>Action:</b> {latest.get('recommended_action', 'continue')}</p><p><b>Notify owner:</b> {latest.get('must_notify_owner', False)}</p></section><section class="card"><h2>Журнал alerts</h2><table><thead><tr><th>Severity</th><th>Topic</th><th>Title</th><th>Source</th><th>Action</th><th>Bots</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""
    )


@app.get("/api/policy-monitor/snapshot")
def snapshot() -> dict[str, Any]:
    return journal().snapshot(limit=50)


@app.post("/api/policy-monitor/run")
def run(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return {"status": "invalid_items"}
    return run_policy_ops(watch_store=watch_store(), journal=journal(), items=[item for item in items if isinstance(item, dict)])


def _row(alert: dict[str, Any]) -> str:
    severity = str(alert.get("severity", "info"))
    return f"<tr><td class='{severity}'>{severity}</td><td>{alert.get('topic', '')}</td><td>{alert.get('title', '')}</td><td>{alert.get('source_domain', '')}</td><td>{alert.get('controller_action', '')}</td><td>{', '.join(alert.get('affected_bots', []))}</td></tr>"
