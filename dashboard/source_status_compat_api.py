"""Stable status contracts used by the Web2 dashboard.

These endpoints normalize canonical persistent services. Empty datasets remain
healthy and are never replaced with demonstration records.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from learning.evidence_learning_bridge import evidence_learning_snapshot
from learning.evidence_vault import EvidenceVault
from learning.learning_memory import LearningMemory


def install_source_status_compat_api(app: FastAPI) -> None:
    if getattr(app.state, "source_status_compat_api_installed", False):
        return
    app.state.source_status_compat_api_installed = True

    existing = {getattr(route, "path", "") for route in app.routes}
    if "/api/evidence-vault/recent" not in existing:

        @app.get("/api/evidence-vault/recent")
        def evidence_recent() -> dict[str, Any]:
            vault = EvidenceVault(Path(os.getenv("EVIDENCE_VAULT_DB", "data/evidence_vault.sqlite3")))
            memory = LearningMemory(Path(os.getenv("LEARNING_MEMORY_DB", "data/learning_memory.sqlite3")))
            snap = evidence_learning_snapshot(vault, memory)
            evidence = snap.get("evidence", {}) if isinstance(snap.get("evidence"), dict) else {}
            items = evidence.get("recent_decisions", [])
            if not isinstance(items, list):
                items = []
            return {
                "status": "ok",
                "source": "evidence_vault",
                "items": items,
                "records": items,
                "events": items,
                "summary": {
                    "decision_count": int(evidence.get("decision_count", len(items)) or 0),
                    "evidence_count": int(evidence.get("evidence_count", 0) or 0),
                    "outcome_count": int(evidence.get("outcome_count", 0) or 0),
                    "source_count": int(evidence.get("source_count", 0) or 0),
                },
                "source_reputation": snap.get("source_reputation", []),
            }
