"""Small compatibility adapter for FastAPI lifecycle registration.

Recent FastAPI/Starlette combinations may omit ``FastAPI.add_event_handler``
while still exposing the router startup/shutdown handler lists. SharipovAI has
older bounded-runtime installers that use that public method. Keep one adapter
at the package boundary instead of weakening each installer independently.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI


def ensure_fastapi_lifecycle_compatibility() -> None:
    if callable(getattr(FastAPI, "add_event_handler", None)):
        return

    def add_event_handler(self: FastAPI, event_type: str, handler: Callable[..., Any]) -> None:
        clean_event = str(event_type).strip().lower()
        if clean_event not in {"startup", "shutdown"}:
            raise ValueError(f"unsupported lifecycle event: {event_type}")
        router = getattr(self, "router", None)
        handlers = getattr(router, f"on_{clean_event}", None) if router is not None else None
        if not isinstance(handlers, list):
            raise RuntimeError(f"FastAPI router does not expose on_{clean_event} handlers")
        handlers.append(handler)

    setattr(FastAPI, "add_event_handler", add_event_handler)


__all__ = ["ensure_fastapi_lifecycle_compatibility"]
