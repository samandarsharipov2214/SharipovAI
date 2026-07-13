"""Compatibility helpers for FastAPI/Starlette lifecycle registration.

Some supported runtime combinations expose ``add_event_handler`` only on the
application router.  Installers use the historical application-level method,
so this shim restores that small API without changing lifecycle semantics.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


LifecycleHandler = Callable[[], Any]


def ensure_event_handler_compat(app: Any) -> bool:
    """Ensure ``app.add_event_handler`` exists.

    Returns ``True`` when a compatibility method was installed and ``False``
    when the application already provided the method.
    """

    existing = getattr(app, "add_event_handler", None)
    if callable(existing):
        return False

    router = getattr(app, "router", None)
    if router is None:
        raise RuntimeError("FastAPI application router is unavailable")

    router_registrar = getattr(router, "add_event_handler", None)
    if callable(router_registrar):
        setattr(app, "add_event_handler", router_registrar)
        return True

    def add_event_handler(event_type: str, handler: LifecycleHandler) -> None:
        if event_type == "startup":
            handlers = getattr(router, "on_startup", None)
        elif event_type == "shutdown":
            handlers = getattr(router, "on_shutdown", None)
        else:
            raise ValueError(f"unsupported lifecycle event: {event_type}")
        if not isinstance(handlers, list):
            raise RuntimeError(f"router does not expose {event_type} lifecycle handlers")
        handlers.append(handler)

    setattr(app, "add_event_handler", add_event_handler)
    return True


__all__ = ["ensure_event_handler_compat"]
