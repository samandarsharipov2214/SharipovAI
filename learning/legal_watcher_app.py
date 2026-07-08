"""SharipovAI legal watcher API.

Run with:
    python -m uvicorn learning.legal_watcher_app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI

from .legal_source_watcher import LegalWatchStateStore, legal_source_registry, watch_with_store


app = FastAPI(title="SharipovAI Legal Watcher")


def legal_watch_store() -> LegalWatchStateStore:
    return LegalWatchStateStore(Path(os.getenv("LEGAL_WATCH_STATE_FILE", "data/legal_watch_state.json")))


@app.get("/api/legal/watch/sources")
def watch_sources(region: str = "global") -> dict[str, Any]:
    return legal_source_registry(region)


@app.post("/api/legal/watch/run")
def run_legal_watch(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return {"status": "invalid_items"}
    return watch_with_store([item for item in items if isinstance(item, dict)], legal_watch_store())
