"""Background real-news refresh for SharipovAI.

This module keeps Social News Monitor from falling back to static demo-looking
state. It only reads allowlisted public RSS sources and never places orders.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from .agents import run_news_agents
from .analyzer import analyzed_news_payload
from .rss_reader import read_rss_items, rss_status
from .storage import load_news_state, save_news_state

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LOCK = threading.Lock()
_LAST_STATUS: dict[str, Any] = {"status": "not_started"}


def news_autorun_enabled() -> bool:
    return os.getenv("NEWS_AUTORUN_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def news_refresh_seconds() -> int:
    return max(30, int(os.getenv("NEWS_REFRESH_SECONDS", "180") or 180))


def news_stale_seconds() -> int:
    return max(30, int(os.getenv("NEWS_STALE_SECONDS", "240") or 240))


def news_limit_per_source() -> int:
    return max(1, min(int(os.getenv("NEWS_LIMIT_PER_SOURCE", "5") or 5), 20))


def start_news_autorun() -> dict[str, Any]:
    """Start one background RSS refresh loop."""

    global _THREAD, _LAST_STATUS
    if not news_autorun_enabled():
        _LAST_STATUS = {"status": "disabled", "reason": "NEWS_AUTORUN_ENABLED=0"}
        return dict(_LAST_STATUS)
    if _THREAD and _THREAD.is_alive():
        return {"status": "already_running", "thread_alive": True, **_LAST_STATUS}
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="news-autorefresh", daemon=True)
    _THREAD.start()
    _LAST_STATUS = {"status": "started", "thread_alive": True, "refresh_seconds": news_refresh_seconds()}
    return dict(_LAST_STATUS)


def news_autorun_status() -> dict[str, Any]:
    return {"enabled": news_autorun_enabled(), "thread_alive": bool(_THREAD and _THREAD.is_alive()), **_LAST_STATUS}


def stop_news_autorun() -> dict[str, Any]:
    _STOP.set()
    return {"status": "stopping", "thread_alive": bool(_THREAD and _THREAD.is_alive())}


def refresh_news_now(*, reason: str = "manual", limit_per_source: int | None = None) -> dict[str, Any]:
    """Fetch RSS sources now, analyze, save state, and return detailed status."""

    global _LAST_STATUS
    started = int(time.time())
    with _LOCK:
        try:
            limit = int(limit_per_source or news_limit_per_source())
            result = read_rss_items(limit_per_source=limit)
            raw_items = list(result.get("items", []))
            analyzed = analyzed_news_payload(raw_items)
            agents = run_news_agents(raw_items)
            state = load_news_state()
            state["news"] = analyzed
            state["agents"] = agents
            state["rss_reader"] = result.get("rss", rss_status())
            state["rss_enabled"] = True
            state["last_refresh_at"] = started
            state["last_refresh_reason"] = reason
            state["last_refresh_item_count"] = len(raw_items)
            state["last_refresh_errors"] = result.get("errors", [])
            state["source_mode"] = "real_rss" if raw_items else "rss_empty_no_demo_replacement"
            save_news_state(state)
            _LAST_STATUS = {
                "status": "running" if reason == "autorun" else "refreshed",
                "last_refresh_at": started,
                "last_refresh_age_seconds": 0,
                "reason": reason,
                "item_count": len(raw_items),
                "errors": result.get("errors", []),
                "refresh_seconds": news_refresh_seconds(),
            }
            return {"status": "ok", "reason": reason, "rss": result.get("rss", {}), "item_count": len(raw_items), "errors": result.get("errors", []), "news": analyzed, "agents": agents}
        except Exception as exc:  # pragma: no cover - production safety
            _LAST_STATUS = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "last_refresh_at": started, "reason": reason}
            return dict(_LAST_STATUS)


def refresh_news_if_stale(*, reason: str = "stale_request") -> dict[str, Any]:
    """Refresh if saved news is missing or stale."""

    state = load_news_state()
    last = int(state.get("last_refresh_at", 0) or 0)
    age = int(time.time()) - last if last else 10**9
    if age >= news_stale_seconds():
        return refresh_news_now(reason=reason)
    status = news_autorun_status()
    status.update({"status": "fresh", "last_refresh_at": last, "last_refresh_age_seconds": age, "stale_after_seconds": news_stale_seconds()})
    return status


def _loop() -> None:
    while not _STOP.is_set():
        refresh_news_now(reason="autorun")
        _STOP.wait(news_refresh_seconds())
