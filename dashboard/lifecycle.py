"""Compatibility helpers for FastAPI/Starlette lifecycle registration.

FastAPI releases built on newer Starlette versions may not expose the legacy
``app.add_event_handler`` method. SharipovAI still has several existing runtime
components that use that API. This adapter restores only that narrow lifecycle
contract and delegates to the application's router lists; it does not start
threads during import and it does not change financial settings.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def register_lifecycle_handler(app: Any, event: str, handler: Callable[[], Any]) -> None:
    """Register one startup/shutdown handler across FastAPI versions."""
    event_name = str(event).strip().lower()
    if event_name not in {"startup", "shutdown"}:
        raise ValueError(f"unsupported lifecycle event: {event}")

    router = getattr(app, "router", None)
    handlers = getattr(router, f"on_{event_name}", None) if router is not None else None
    if not isinstance(handlers, list):
        raise RuntimeError(f"application router does not expose on_{event_name}")
    if handler not in handlers:
        handlers.append(handler)


def install_fastapi_lifecycle_compat(app: Any) -> None:
    """Install the removed legacy method on one app instance when necessary."""
    if callable(getattr(app, "add_event_handler", None)):
        return
    if getattr(getattr(app, "state", None), "lifecycle_compat_installed", False):
        return

    def add_event_handler(event: str, handler: Callable[[], Any]) -> None:
        register_lifecycle_handler(app, event, handler)

    setattr(app, "add_event_handler", add_event_handler)
    app.state.lifecycle_compat_installed = True


__all__ = ["install_fastapi_lifecycle_compat", "register_lifecycle_handler"]
