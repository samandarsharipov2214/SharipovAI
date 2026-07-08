"""Dashboard integration for Evidence Vault."""

from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from learning.evidence_learning_bridge import evidence_learning_snapshot, record_decision_outcome_and_learn
from learning.evidence_vault import EvidenceVault
from learning.learning_memory import LearningMemory


def install_evidence_vault_api(app: FastAPI) -> None:
    """Install Evidence Vault endpoints once."""

    if getattr(app.state, "evidence_vault_api_installed", False):
        return
    app.state.evidence_vault_api_installed = True

    def vault() -> EvidenceVault:
        return EvidenceVault(Path(os.getenv("EVIDENCE_VAULT_DB", "data/evidence_vault.sqlite3")))

    def memory() -> LearningMemory:
        return LearningMemory(Path(os.getenv("LEARNING_MEMORY_DB", "data/learning_memory.sqlite3")))

    @app.get("/api/evidence-vault/snapshot")
    def snapshot_api() -> dict[str, Any]:
        return evidence_learning_snapshot(vault(), memory())

    @app.post("/api/evidence-vault/decisions")
    def record_decision_api(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return vault().record_decision(
            actor=str(data.get("actor", "general_controller")),
            decision=str(data.get("decision", "WATCH")),
            topic=str(data.get("topic", "general")),
            confidence=float(data.get("confidence", 50.0)),
            risk_level=str(data.get("risk_level", "MEDIUM")),
            reason=str(data.get("reason", "not provided")),
            evidence=data.get("evidence", []) if isinstance(data.get("evidence", []), list) else [],
            policy_status=str(data.get("policy_status", "unknown")),
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
        )

    @app.get("/api/evidence-vault/decisions/{decision_id}/replay")
    def replay_api(decision_id: str) -> dict[str, Any]:
        return vault().replay_decision(decision_id)

    @app.post("/api/evidence-vault/decisions/{decision_id}/outcome")
    def outcome_api(decision_id: str, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return record_decision_outcome_and_learn(
            vault=vault(),
            memory=memory(),
            decision_id=decision_id,
            outcome=str(data.get("outcome", "unknown")),
            impact_score=float(data.get("impact_score", 0.0)),
            notes=str(data.get("notes", "")),
            learning_signal=str(data.get("learning_signal", "neutral")),
        )

    @app.get("/evidence-vault", response_class=HTMLResponse)
    def evidence_vault_page() -> HTMLResponse:
        return HTMLResponse(_render_evidence(evidence_learning_snapshot(vault(), memory())))


def _render_evidence(snap: dict[str, Any]) -> str:
    evidence = snap.get("evidence", {})
    rows = "".join(_decision_row(item) for item in evidence.get("recent_decisions", [])) or "<tr><td colspan='5'>Пока нет решений.</td></tr>"
    sources = "".join(_source_row(item) for item in evidence.get("source_reputation", [])) or "<tr><td colspan='5'>Пока нет источников.</td></tr>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Evidence Vault</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">EVIDENCE VAULT</span><h1>Память решений и доказательств</h1><p>Здесь видно, почему ИИ принял решение, на каких источниках, и что произошло потом.</p><p><a href="/">Главная</a> · <a href="/api/evidence-vault/snapshot">JSON snapshot</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Decisions</small><b>{evidence.get('decision_count', 0)}</b></div><div class="stat"><small>Evidence</small><b>{evidence.get('evidence_count', 0)}</b></div><div class="stat"><small>Outcomes</small><b>{evidence.get('outcome_count', 0)}</b></div><div class="stat"><small>Sources</small><b>{evidence.get('source_count', 0)}</b></div></div></section><section class="card"><h2>Последние решения</h2><table><thead><tr><th>ID</th><th>Actor</th><th>Decision</th><th>Confidence</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></section><section class="card"><h2>Репутация источников</h2><table><thead><tr><th>Source</th><th>Trust</th><th>Uses</th><th>Confirmed</th><th>Contradicted</th></tr></thead><tbody>{sources}</tbody></table></section></main></body></html>"""


def _decision_row(item: dict[str, Any]) -> str:
    return f"<tr><td>{escape(str(item.get('decision_id', '')))}</td><td>{escape(str(item.get('actor', '')))}</td><td>{escape(str(item.get('decision', '')))}</td><td>{escape(str(item.get('confidence', '')))}</td><td>{escape(str(item.get('reason', '')))}</td></tr>"


def _source_row(item: dict[str, Any]) -> str:
    return f"<tr><td>{escape(str(item.get('source_domain', '')))}</td><td>{escape(str(item.get('trust_score', '')))}</td><td>{escape(str(item.get('uses', '')))}</td><td>{escape(str(item.get('confirmed', '')))}</td><td>{escape(str(item.get('contradicted', '')))}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
