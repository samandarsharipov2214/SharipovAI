"""Dashboard package entrypoint for SharipovAI OS."""

from __future__ import annotations

from .app import app, create_app
from .exceptions import DashboardError

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
