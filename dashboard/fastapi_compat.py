"""Compatibility helpers for supported FastAPI/Starlette versions."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI


def install_fastapi_event_compat() -> bool:
    """Restore ``FastAPI.add_event_handler`` when a newer build omits it.

    SharipovAI installers use synchronous startup/shutdown callbacks. FastAPI's
    existing ``on_event`` decorator remains the source of truth; this shim only
    exposes the older convenience method expected by those installers.
    """

    if callable(getattr(FastAPI, "add_event_handler", None)):
        return False

    def add_event_handler(self: FastAPI, event_type: str, func: Callable[..., Any]) -> None:
        on_event = getattr(self, "on_event", None)
        if not callable(on_event):
            raise RuntimeError("FastAPI runtime exposes neither add_event_handler nor on_event")
        on_event(event_type)(func)

    setattr(FastAPI, "add_event_handler", add_event_handler)
    return True


__all__ = ["install_fastapi_event_compat"]
