"""Bounded non-financial watchdog for the existing SharipovAI runtime.

The watchdog consumes SystemHealthCenter snapshots and may execute only
explicitly registered, in-process, non-financial recovery callbacks. It never
changes trading flags, submits orders, activates failover, restores a database,
or runs arbitrary shell commands.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Callable

from fastapi import FastAPI

from .lifecycle_compat import ensure_event_handler_compat


SafeAction = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class WatchdogActionResult:
    component: str
    action: str
    status: str
    attempted_at_ms: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SystemWatchdogManager:
    """Observe health transitions and apply bounded safe callbacks."""

    SAFE_ACTIONS = {
        "ai_organs": "refresh_ai_organs",
        "market": "restart_public_market_worker",
        "news": "refresh_news_runtime",
    }

    FORBIDDEN_COMPONENTS = {"security", "database", "backup", "telegram", "storage"}

    def __init__(
        self,
        app: FastAPI,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.app = app
        self.clock = clock or time.time
        self.sleeper = sleeper or time.sleep
        self.enabled = _truthy("SYSTEM_WATCHDOG_ENABLED")
        self.interval_seconds = _bounded_float("SYSTEM_WATCHDOG_INTERVAL_SECONDS", 30.0, 10.0, 300.0)
        self.max_attempts = int(_bounded_float("SYSTEM_WATCHDOG_MAX_ATTEMPTS", 3.0, 1.0, 10.0))
        self.window_seconds = _bounded_float("SYSTEM_WATCHDOG_WINDOW_SECONDS", 900.0, 60.0, 86400.0)
        self.cooldown_seconds = _bounded_float("SYSTEM_WATCHDOG_COOLDOWN_SECONDS", 120.0, 10.0, 3600.0)
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._last_attempt: dict[str, float] = {}
        self._last_status: dict[str, str] = {}
        self._safe_mode_components: set[str] = set()
        self._history: deque[WatchdogActionResult] = deque(maxlen=200)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="system-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def tick(self) -> dict[str, Any]:
        center = getattr(self.app.state, "system_health_center", None)
        if center is None:
            return self._snapshot(last_error="SystemHealthCenter is not installed")
        health = center.snapshot()
        for component in health.get("components", []):
            name = str(component.get("component", ""))
            status = str(component.get("status", "blocked"))
            previous = self._last_status.get(name)
            self._last_status[name] = status
            if status == "healthy":
                self._safe_mode_components.discard(name)
                continue
            if name in self.FORBIDDEN_COMPONENTS:
                self._record(name, "advisory_only", "blocked", "automatic recovery forbidden")
                if status == "blocked":
                    self._safe_mode_components.add(name)
                continue
            if previous == status and not self._cooldown_elapsed(name):
                continue
            self._attempt_component(name, status)
        snapshot = self._snapshot(health=health)
        self._persist(snapshot)
        return snapshot

    def status(self) -> dict[str, Any]:
        return self._snapshot()

    def reset_component(self, component: str) -> dict[str, Any]:
        component = str(component).strip()
        with self._lock:
            self._attempts.pop(component, None)
            self._last_attempt.pop(component, None)
            self._safe_mode_components.discard(component)
        result = self._snapshot()
        self._persist(result)
        return result

    def _attempt_component(self, component: str, status: str) -> None:
        action_name = self.SAFE_ACTIONS.get(component)
        if not action_name:
            self._record(component, "no_safe_action", "skipped", f"status={status}")
            return
        now = self.clock()
        attempts = self._attempts[component]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.max_attempts:
            self._safe_mode_components.add(component)
            self._record(component, action_name, "circuit_open", "maximum attempts exceeded")
            return
        callback = self._resolve_action(action_name)
        if callback is None:
            self._record(component, action_name, "unavailable", "safe callback is not registered")
            return
        attempts.append(now)
        self._last_attempt[component] = now
        try:
            callback()
        except Exception as exc:
            self._record(component, action_name, "failed", f"{type(exc).__name__}: {exc}")
            if len(attempts) >= self.max_attempts:
                self._safe_mode_components.add(component)
            return
        self._record(component, action_name, "completed", "safe callback completed")

    def _resolve_action(self, action_name: str) -> SafeAction | None:
        callbacks = getattr(self.app.state, "watchdog_safe_actions", None)
        if isinstance(callbacks, dict):
            callback = callbacks.get(action_name)
            if callable(callback):
                return callback
        if action_name == "refresh_ai_organs":
            monitor = getattr(self.app.state, "ai_organ_runtime_monitor", None)
            callback = getattr(monitor, "refresh", None)
            return callback if callable(callback) else None
        if action_name == "restart_public_market_worker":
            worker = getattr(self.app.state, "bybit_websocket_worker", None)
            start = getattr(worker, "start", None)
            stop = getattr(worker, "stop", None)
            if callable(start) and callable(stop):
                def restart() -> None:
                    stop()
                    start()
                return restart
        if action_name == "refresh_news_runtime":
            network = getattr(self.app.state, "news_agent_network", None)
            cycle = getattr(network, "cycle", None)
            return cycle if callable(cycle) else None
        return None

    def _cooldown_elapsed(self, component: str) -> bool:
        last = self._last_attempt.get(component)
        return last is None or self.clock() - last >= self.cooldown_seconds

    def _record(self, component: str, action: str, status: str, detail: str) -> None:
        result = WatchdogActionResult(component, action, status, int(self.clock() * 1000), detail)
        with self._lock:
            self._history.append(result)
        database = getattr(self.app.state, "project_database", None)
        append_event = getattr(database, "append_event", None)
        if callable(append_event):
            try:
                append_event(
                    "system_watchdog",
                    "recovery_action",
                    component,
                    result.to_dict(),
                )
            except Exception:
                pass

    def _snapshot(self, *, health: dict[str, Any] | None = None, last_error: str = "") -> dict[str, Any]:
        with self._lock:
            history = [item.to_dict() for item in list(self._history)[-50:]]
            safe_mode_components = sorted(self._safe_mode_components)
            attempts = {key: len(value) for key, value in self._attempts.items()}
        return {
            "status": "safe_mode" if safe_mode_components else "running" if self.enabled else "disabled",
            "enabled": self.enabled,
            "thread_running": bool(self._thread and self._thread.is_alive()),
            "safe_mode": bool(safe_mode_components),
            "safe_mode_components": safe_mode_components,
            "attempt_counts": attempts,
            "max_attempts": self.max_attempts,
            "window_seconds": self.window_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "automatic_financial_recovery": False,
            "automatic_failover": False,
            "health_status": (health or {}).get("status"),
            "last_error": last_error,
            "history": history,
        }

    def _persist(self, payload: dict[str, Any]) -> None:
        database = getattr(self.app.state, "project_database", None)
        put_json = getattr(database, "put_json", None)
        if callable(put_json):
            try:
                put_json("system_runtime", "watchdog", payload)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.tick()
            except Exception as exc:
                self._record("watchdog", "tick", "failed", f"{type(exc).__name__}: {exc}")


def install_system_watchdog(app: FastAPI) -> None:
    if getattr(app.state, "system_watchdog_installed", False):
        return
    ensure_event_handler_compat(app)
    app.state.system_watchdog_installed = True
    manager = SystemWatchdogManager(app)
    app.state.system_watchdog = manager
    app.add_event_handler("startup", manager.start)
    app.add_event_handler("shutdown", manager.stop)

    @app.get("/api/system/watchdog")
    def watchdog_status() -> dict[str, Any]:
        return manager.status()

    @app.post("/api/system/watchdog/tick")
    def watchdog_tick() -> dict[str, Any]:
        return manager.tick()

    @app.post("/api/system/watchdog/reset/{component}")
    def watchdog_reset(component: str) -> dict[str, Any]:
        return manager.reset_component(component)


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


__all__ = ["SystemWatchdogManager", "WatchdogActionResult", "install_system_watchdog"]
