from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard.lifecycle_compat import ensure_event_handler_compat


def test_uses_router_add_event_handler_when_app_method_is_missing() -> None:
    calls: list[tuple[str, object]] = []

    class Router:
        def add_event_handler(self, event_type: str, handler: object) -> None:
            calls.append((event_type, handler))

    app = SimpleNamespace(router=Router())
    handler = lambda: None

    assert ensure_event_handler_compat(app) is True
    app.add_event_handler("startup", handler)

    assert calls == [("startup", handler)]


def test_falls_back_to_router_lifecycle_lists() -> None:
    router = SimpleNamespace(on_startup=[], on_shutdown=[])
    app = SimpleNamespace(router=router)
    startup = lambda: None
    shutdown = lambda: None

    assert ensure_event_handler_compat(app) is True
    app.add_event_handler("startup", startup)
    app.add_event_handler("shutdown", shutdown)

    assert router.on_startup == [startup]
    assert router.on_shutdown == [shutdown]


def test_rejects_unknown_lifecycle_event_in_list_fallback() -> None:
    app = SimpleNamespace(router=SimpleNamespace(on_startup=[], on_shutdown=[]))
    ensure_event_handler_compat(app)

    with pytest.raises(ValueError, match="unsupported lifecycle event"):
        app.add_event_handler("reload", lambda: None)
