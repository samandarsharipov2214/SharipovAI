"""Dashboard package for SharipovAI OS."""

from __future__ import annotations

from collections.abc import Callable

from runner import SharipovAIRunner

from .app import create_app as _create_base_app
from .demo_api import install_demo_api
from .exceptions import DashboardError
from .exchange_api import install_exchange_api


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None):
    """Create dashboard app with package-level safe exchange and demo APIs installed."""

    app_instance = _create_base_app(runner_factory=runner_factory)
    install_exchange_api(app_instance)
    install_demo_api(app_instance)
    return app_instance


app = create_app()

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
