"""Evidence Vault API and dashboard.

Run with:
    python -m uvicorn learning.evidence_vault_app:app --reload
"""

from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from .evidence_learning_bridge import evidence_learning_snapshot, record_decision_outcome_and_learn
from .evidence_vault import EvidenceVault
from .learning_memory import LearningMemory


app = FastAPI(title="SharipovAI Evidence Vault")


def vault() -> EvidenceVault:
    return EvidenceVault(Path(os.getenv("EVIDENCE_VAULT_DB", "data/evidence_vault.sqlite3")))


def memory() -> LearningMemory:
    return LearningMemory(Path(os.getenv("LEARNING_MEMORY_DB", "data/learning_memory.sqlite3")))


@app.get("/api/evidence-vault/snapshot")
def snapshot_api() -> dict[str, Any]:
    return evidence_learning_snapshot(vault(), memory())


@app.post("/api/evidence-vault/decisions")
def record_decision_api(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return vault().record_decision(
        actor=str(payload.get("actor", "general_controller")),
        decision=str(payload.get("decision", "WATCH")),
        topic=str(payload.get("topic", "general")),
        confidence=float(payload.get("confidence", 50.0)),
        risk_level=str(payload.get("risk_level", "MEDIUM")),
        reason=str(payload.get("reason", "not provided")),
        evidence=payload.get("evidence", []) if isinstance(payload.get("evidence", []), list) else [],
        policy_status=str(payload.get("policy_status", "unknown")),
        metadata=payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {},
    )


@app.get("/api/evidence-vault/decisions")
def decisions_api(limit: int = 50) -> dict[str, Any]:
    return {"status": "ok", "decisions": vault().decisions(limit=limit)}


@app.get("/api/evidence-vault/decisions/{decision_id}/replay")
def replay_api(decision_id: str) -> dict[str, Any]:
    return vault().replay_decision(decision_id)


@app.post("/api/evidence-vault/decisions/{decision_id}/outcome")
def outcome_api(decision_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return record_decision_outcome_and_learn(
        vault=vault(),
        memory=memory(),
        decision_id=decision_id,
        outcome=str(payload.get("outcome", "unknown")),
        impact_score=float(payload.get("impact_score", 0.0)),
        notes=str(payload.get("notes", "")),
        learning_signal=str(payload.get("learning_signal", "neutral")),
    )


@app.get("/api/evidence-vault/sources")
def sources_api() -> dict[str, Any]:
    return vault().source_reputation()


@app.get("/evidence-vault", response_class=HTMLResponse)
def evidence_vault_page() -> HTMLResponse:
    snap = evidence_learning_snapshot(vault(), memory())
    evidence = snap.get("evidence", {})
    rows = "".join(_decision_row(item) for item in evidence.get("recent_decisions", [])) or "<tr><td colspan='5'>Пока нет решений.</td></tr>"
    sources = "".join(_source_row(item) for item in evidence.get("source_reputation", [])) or "<tr><td colspan='5'>Пока нет источников.</td></tr>"
    return HTMLResponse(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Evidence Vault</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">EVIDENCE VAULT</span><h1>Память решений и доказательств</h1><p>Здесь хранится почему ИИ принял решение, на каких источниках, и что произошло потом.</p><p><a href="/api/evidence-vault/snapshot">JSON snapshot</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Decisions</small><b>{evidence.get('decision_count', 0)}</b></div><div class="stat"><small>Evidence</small><b>{evidence.get('evidence_count', 0)}</b></div><div class="stat"><small>Outcomes</small><b>{evidence.get('outcome_count', 0)}</b></div><div class="stat"><small>Sources</small><b>{evidence.get('source_count', 0)}</b></div></div></section><section class="card"><h2>Последние решения</h2><table><thead><tr><th>ID</th><th>Actor</th><th>Decision</th><th>Confidence</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></section><section class="card"><h2>Репутация источников</h2><table><thead><tr><th>Source</th><th>Trust</th><th>Uses</th><th>Confirmed</th><th>Contradicted</th></tr></thead><tbody>{sources}</tbody></table></section></main></body></html>"""
    )


def _decision_row(item: dict[str, Any]) -> str:
    return f"<tr><td>{escape(str(item.get('decision_id', '')))}</td><td>{escape(str(item.get('actor', '')))}</td><td>{escape(str(item.get('decision', '')))}</td><td>{escape(str(item.get('confidence', '')))}</td><td>{escape(str(item.get('reason', '')))}</td></tr>"


def _source_row(item: dict[str, Any]) -> str:
    return f"<tr><td>{escape(str(item.get('source_domain', '')))}</td><td>{escape(str(item.get('trust_score', '')))}</td><td>{escape(str(item.get('uses', '')))}</td><td>{escape(str(item.get('confirmed', '')))}</td><td>{escape(str(item.get('contradicted', '')))}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
