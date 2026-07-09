"""Simple JSON storage for Social News Monitor state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .analyzer import analyzed_news_payload
from .sources import sources_payload


def state_path() -> Path:
    """Return state file path."""

    return Path(os.getenv("NEWS_MONITOR_STATE_FILE", "data/news_monitor_state.json"))


def load_news_state() -> dict[str, Any]:
    """Load saved monitor state or return an honest empty default."""

    path = state_path()
    if not path.exists():
        return default_news_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_news_state()
    if not isinstance(data, dict):
        return default_news_state()
    base = default_news_state()
    base.update(data)
    return base


def save_news_state(state: dict[str, Any]) -> dict[str, Any]:
    """Persist monitor state."""

    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def default_news_state() -> dict[str, Any]:
    """Return an honest default state with no fake live news."""

    return {
        "sources": sources_payload(),
        "news": analyzed_news_payload([]),
        "telegram_enabled": False,
        "x_enabled": False,
        "rss_enabled": True,
        "source_mode": "empty_waiting_real_refresh",
        "last_refresh_at": 0,
        "last_refresh_item_count": 0,
        "last_refresh_errors": [],
        "message": "Social News Monitor включён, но ждёт реальный RSS/official refresh. Статичные demo-новости не подставляются как live.",
    }
