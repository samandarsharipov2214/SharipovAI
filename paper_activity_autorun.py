"""Background autorun loop for market-backed virtual account execution.

Runs only virtual-account ticks. It never places live orders.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from market_paper_engine import PaperActivityEngine
from paper_activity_engine import paper_tick_seconds


_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LAST_STATUS: dict[str, Any] = {"status": "not_started"}


def autorun_enabled() -> bool:
    raw = os.getenv(
        "VIRTUAL_ACCOUNT_AUTORUN_ENABLED",
        os.getenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "1"),
    )
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def start_paper_activity_autorun() -> dict[str, Any]:
    """Start one background virtual-account activity loop if enabled."""

    global _THREAD, _LAST_STATUS
    if not autorun_enabled():
        _LAST_STATUS = {"status": "disabled", "reason": "VIRTUAL_ACCOUNT_AUTORUN_ENABLED=0"}
        return dict(_LAST_STATUS)
    if _THREAD and _THREAD.is_alive():
        return {"status": "already_running", "thread_alive": True, **_LAST_STATUS}
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="market-paper-autorun", daemon=True)
    _THREAD.start()
    _LAST_STATUS = {"status": "started", "thread_alive": True, "tick_seconds": paper_tick_seconds()}
    return dict(_LAST_STATUS)


def paper_activity_autorun_status() -> dict[str, Any]:
    return {"enabled": autorun_enabled(), "thread_alive": bool(_THREAD and _THREAD.is_alive()), **_LAST_STATUS}


def stop_paper_activity_autorun() -> dict[str, Any]:
    _STOP.set()
    return {"status": "stopping", "thread_alive": bool(_THREAD and _THREAD.is_alive())}


def _loop() -> None:
    global _LAST_STATUS
    engine = PaperActivityEngine()
    while not _STOP.is_set():
        try:
            catch_up = engine.catch_up(max_ticks=1)
            state = engine.state()
            _LAST_STATUS = {
                "status": "running",
                "last_loop_at": int(time.time()),
                "last_catch_up": catch_up,
                "summary": state.get("summary", {}),
                "engine": "market_backed_virtual_account",
                "tick_seconds": paper_tick_seconds(),
            }
        except Exception as exc:  # pragma: no cover - production safety
            _LAST_STATUS = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "last_loop_at": int(time.time()),
            }
        _STOP.wait(paper_tick_seconds())
