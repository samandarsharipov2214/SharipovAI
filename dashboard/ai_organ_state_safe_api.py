"""Safe installer for canonical AI-organ runtime monitoring.

The monitor is observability-only. A broken evidence probe must never prevent the
FastAPI application from starting. All organ probes are inherited from the
canonical monitor so production and tests use one runtime truth.
"""
from __future__ import annotations

import importlib
import importlib.util
import threading
from typing import Any

from fastapi import FastAPI

from storage import ProjectDatabase

from .ai_organ_state_api import AIOrganRuntimeMonitor
from .lifecycle_compat import ensure_event_handler_compat


class SafeAIOrganRuntimeMonitor(AIOrganRuntimeMonitor):
    """Failure-isolated wrapper around the canonical runtime monitor."""

    def start(self) -> None:
        try:
            self.refresh()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._last_error = error
            self._record_monitor_event(
                "startup_error",
                {"error": error, "checked_at_ms": self.clock_ms()},
            )
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ai-organ-runtime-monitor", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.refresh()
            except Exception as exc:
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                self._record_monitor_event(
                    "refresh_error",
                    {"error": self._last_error, "checked_at_ms": self.clock_ms()},
                )

    def _record_monitor_event(self, event_id: str, payload: dict[str, Any]) -> None:
        try:
            self.database.append_event(
                "system_runtime",
                "ai_organ_monitor",
                event_id,
                payload,
            )
        except Exception:
            # Evidence persistence must not become a second startup/runtime failure.
            pass


def install_ai_organ_state_api(app: FastAPI) -> None:
    if getattr(app.state, "ai_organ_state_api_installed", False):
        return
    ensure_event_handler_compat(app)
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before AI organ monitor")
    app.state.ai_organ_state_api_installed = True
    monitor = SafeAIOrganRuntimeMonitor(app, database)
    app.state.ai_organ_runtime_monitor = monitor
    app.add_event_handler("startup", monitor.start)
    app.add_event_handler("shutdown", monitor.stop)

    @app.get("/api/system/ai-organs")
    def ai_organs_status() -> dict[str, Any]:
        return monitor.snapshot()

    @app.post("/api/system/ai-organs/refresh")
    def refresh_ai_organs() -> dict[str, Any]:
        return monitor.refresh()


def _module_available(name: str) -> bool:
    """Compatibility helper retained for existing runtime contract tests."""
    try:
        return importlib.util.find_spec(name) is not None
    except (AttributeError, ImportError, ModuleNotFoundError, ValueError):
        return False


def _module_has_callable(module_name: str, attribute: str) -> bool:
    """Compatibility helper; canonical probes no longer rely on module presence."""
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False
    return callable(getattr(module, attribute, None))


__all__ = [
    "SafeAIOrganRuntimeMonitor",
    "_module_available",
    "_module_has_callable",
    "install_ai_organ_state_api",
]
