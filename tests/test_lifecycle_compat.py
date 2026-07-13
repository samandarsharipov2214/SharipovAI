from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard.lifecycle import install_fastapi_lifecycle_compat, register_lifecycle_handler


class Router:
    def __init__(self) -> None:
        self.on_startup: list[object] = []
        self.on_shutdown: list[object] = []


class AppWithoutLegacyLifecycle:
    def __init__(self) -> None:
        self.router = Router()
        self.state = SimpleNamespace()


def test_compat_installs_missing_add_event_handler() -> None:
    app = AppWithoutLegacyLifecycle()

    def start() -> None:
        return None

    def stop() -> None:
        return None

    install_fastapi_lifecycle_compat(app)
    assert callable(app.add_event_handler)
    app.add_event_handler("startup", start)
    app.add_event_handler("shutdown", stop)
    assert app.router.on_startup == [start]
    assert app.router.on_shutdown == [stop]


def test_registration_is_idempotent() -> None:
    app = AppWithoutLegacyLifecycle()

    def start() -> None:
        return None

    register_lifecycle_handler(app, "startup", start)
    register_lifecycle_handler(app, "startup", start)
    assert app.router.on_startup == [start]


def test_invalid_lifecycle_event_is_rejected() -> None:
    app = AppWithoutLegacyLifecycle()
    with pytest.raises(ValueError):
        register_lifecycle_handler(app, "reload", lambda: None)


def test_dashboard_entrypoint_installs_compat_before_monitoring() -> None:
    source = (pytest.importorskip("pathlib").Path(__file__).resolve().parents[1] / "dashboard" / "__init__.py").read_text(encoding="utf-8")
    compat = source.index("install_fastapi_lifecycle_compat(app)")
    ai_monitor = source.index("install_ai_organ_state_api(app)")
    watchdog = source.index("install_system_watchdog(app)")
    assert compat < ai_monitor < watchdog
