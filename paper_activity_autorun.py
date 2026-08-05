"""Deprecated background loop for the legacy virtual account.

The canonical runtime is ``CouncilAuthorizedPaperLoop``. This compatibility
module is permanently disabled: environment variables cannot reactivate it, it
is excluded from health and learning, and it never places live orders.
"""
from __future__ import annotations

import threading
from typing import Any

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LAST_STATUS: dict[str, Any] = {
    "status": "deprecated",
    "enabled": False,
    "thread_alive": False,
    "deprecated": True,
    "source_of_truth": "autonomous_paper",
    "reason": "legacy PaperActivityEngine autorun is permanently disabled",
}


def autorun_enabled() -> bool:
    """Return False unconditionally; legacy runtime cannot be reactivated."""
    return False


def start_paper_activity_autorun() -> dict[str, Any]:
    """Preserve the old API while refusing to start a duplicate runtime."""
    return paper_activity_autorun_status()


def paper_activity_autorun_status() -> dict[str, Any]:
    return {
        **_LAST_STATUS,
        "enabled": False,
        "thread_alive": False,
        "deprecated": True,
        "excluded_from_health": True,
        "excluded_from_learning": True,
        "mutation_authority": False,
    }


def stop_paper_activity_autorun() -> dict[str, Any]:
    _STOP.set()
    return {"status": "deprecated", "thread_alive": False, "deprecated": True}


def _loop() -> None:
    """No-op retained only for import compatibility."""
    return None


__all__ = [
    "autorun_enabled",
    "paper_activity_autorun_status",
    "start_paper_activity_autorun",
    "stop_paper_activity_autorun",
]
