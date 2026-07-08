"""Unified legal monitor cycle API.

Run with:
    python -m uvicorn learning.legal_monitor_cycle_app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI

from .legal_feed_fetcher import legal_feed_registry, run_legal_monitor_cycle
from .legal_source_watcher import LegalWatchStateStore


app = FastAPI(title="SharipovAI Legal Monitor Cycle")


def state_store() -> LegalWatchStateStore:
    return LegalWatchStateStore(Path(os.getenv("LEGAL_WATCH_STATE_FILE", "data/legal_watch_state.json")))


@app.get("/api/legal/cycle/feeds")
def feeds(region: str = "global") -> dict[str, Any]:
    return legal_feed_registry(region)


@app.post("/api/legal/cycle/run")
def run_cycle(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    use_live_feeds = bool(payload.get("use_live_feeds", False))
    region = str(payload.get("region", "global"))
    fetched_items = payload.get("items", [])
    if not isinstance(fetched_items, list):
        return {"status": "invalid_items"}
    feed_registry = legal_feed_registry(region)
    selected_feeds = feed_registry.get("feeds", []) if use_live_feeds else []
    return run_legal_monitor_cycle(
        feeds=selected_feeds,
        store=state_store(),
        fetched_items=[item for item in fetched_items if isinstance(item, dict)],
    )
