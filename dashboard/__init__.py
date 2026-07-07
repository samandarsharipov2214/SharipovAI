"""Dashboard package for SharipovAI OS."""

from .app import create_app
from .exceptions import DashboardError

__all__: tuple[str, ...] = ("DashboardError", "create_app")
