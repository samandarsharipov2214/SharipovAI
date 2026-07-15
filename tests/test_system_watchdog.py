from __future__ import annotations

from fastapi import FastAPI

from dashboard.lifecycle_compat import ensure_event_handler_compat
from dashboard.system_watchdog import SystemWatchdogManager, install_system_watchdog


class FakeDatabase:
    def __init__(self) -> None:
        self.events = []
        self.values = []

    def append_event(self, *args):
        self.events.append(args)

    def put_json(self, *args):
        self.values.append(args)


class FakeCenter:
    def __init__(self, components):
        self.components = components

    def snapshot(self):
        return {"status": "degraded", "components": self.components}


def app_with(components):
    app = FastAPI()
    app.state.system_health_center = FakeCenter(components)
    app.state.project_database = FakeDatabase()
    return app


def test_watchdog_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_WATCHDOG_ENABLED", raising=False)
    manager = SystemWatchdogManager(app_with([]))
    assert manager.status()["status"] == "disabled"
    assert manager.status()["automatic_financial_recovery"] is False
    assert manager.status()["automatic_failover"] is False


def test_safe_callback_runs_for_ai_organs(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_WATCHDOG_ENABLED", "1")
    calls = []
    app = app_with([{"component": "ai_organs", "status": "degraded"}])
    app.state.watchdog_safe_actions = {"refresh_ai_organs": lambda: calls.append("refresh")}
    manager = SystemWatchdogManager(app, clock=lambda: 1000.0)
    result = manager.tick()
    assert calls == ["refresh"]
    assert result["history"][-1]["status"] == "completed"


def test_security_is_advisory_only(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_WATCHDOG_ENABLED", "1")
    app = app_with([{"component": "security", "status": "blocked"}])
    manager = SystemWatchdogManager(app, clock=lambda: 1000.0)
    result = manager.tick()
    assert result["safe_mode"] is True
    assert result["history"][-1]["action"] == "advisory_only"
    assert result["history"][-1]["status"] == "blocked"


def test_circuit_breaker_opens_after_bounded_failures(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_WATCHDOG_ENABLED", "1")
    monkeypatch.setenv("SYSTEM_WATCHDOG_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("SYSTEM_WATCHDOG_COOLDOWN_SECONDS", "10")
    now = [1000.0]
    app = app_with([{"component": "market", "status": "degraded"}])

    def fail():
        raise RuntimeError("stream failed")

    app.state.watchdog_safe_actions = {"restart_public_market_worker": fail}
    manager = SystemWatchdogManager(app, clock=lambda: now[0])
    manager.tick()
    now[0] += 11
    manager.tick()
    now[0] += 11
    result = manager.tick()
    assert result["safe_mode"] is True
    assert "market" in result["safe_mode_components"]
    assert result["history"][-1]["status"] == "circuit_open"


def test_reset_clears_component_circuit(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_WATCHDOG_ENABLED", "1")
    app = app_with([])
    manager = SystemWatchdogManager(app)
    manager._safe_mode_components.add("market")
    result = manager.reset_component("market")
    assert result["safe_mode"] is False


def test_installer_is_idempotent(monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_WATCHDOG_ENABLED", raising=False)
    app = FastAPI()
    assert ensure_event_handler_compat(app) is True
    install_system_watchdog(app)
    install_system_watchdog(app)
    paths = [route.path for route in app.routes]
    assert paths.count("/api/system/watchdog") == 1
    assert paths.count("/api/system/watchdog/tick") == 1
    assert paths.count("/api/system/watchdog/reset/{component}") == 1
