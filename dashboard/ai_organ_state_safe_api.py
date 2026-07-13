"""Safe installer for AI-organ runtime monitoring.

The monitor is observability-only. A broken evidence probe must never prevent the
FastAPI application from starting, and module checks must support both modules
and packages.
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
    """Failure-isolated monitor used by the production dashboard."""

    def start(self) -> None:
        try:
            self.refresh()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._last_error = error
            try:
                self.database.append_event(
                    "ai_organ_monitor_startup_error",
                    {"error": error, "checked_at_ms": self.clock_ms()},
                )
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ai-organ-runtime-monitor", daemon=True)
        self._thread.start()

    def _risk_engine(self) -> tuple[list[str], list[str]]:
        evidence: list[str] = []
        blockers: list[str] = []
        if _module_has_callable("trading_intelligence", "trade_gate"):
            evidence.append("trade_gate_callable")
        elif _module_available("trading_candidate"):
            evidence.append("canonical_trading_candidate_validator")
        else:
            blockers.append("critical: no canonical trade validation module found")
        try:
            max_notional = float(__import__("os").getenv("EXECUTION_MAX_NOTIONAL_USDT", "25"))
            if 0 < max_notional <= 1000:
                evidence.append(f"execution_notional_cap={max_notional:g}")
            else:
                blockers.append("critical: execution notional cap is invalid")
        except (TypeError, ValueError):
            blockers.append("critical: execution notional cap is invalid")
        return evidence, blockers

    def _decision_quality(self) -> tuple[list[str], list[str]]:
        evidence: list[str] = []
        blockers: list[str] = []
        for module_name in ("trading_candidate", "exchange_connector.preview_candidate_bridge"):
            if _module_available(module_name):
                evidence.append(module_name)
            else:
                blockers.append(f"critical: decision evidence module missing: {module_name}")
        return evidence, blockers


def install_ai_organ_state_api(app: FastAPI) -> None:
    if getattr(app.state, "ai_organ_state_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before AI organ monitor")
    ensure_event_handler_compat(app)
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
    try:
        return importlib.util.find_spec(name) is not None
    except (AttributeError, ImportError, ModuleNotFoundError, ValueError):
        return False


def _module_has_callable(module_name: str, attribute: str) -> bool:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False
    return callable(getattr(module, attribute, None))


__all__ = ["SafeAIOrganRuntimeMonitor", "install_ai_organ_state_api"]
