"""Dashboard package entrypoint for SharipovAI OS.

Render starts ``uvicorn dashboard:app``. Feature installers placed here must be
idempotent so Codex/tests may also import ``dashboard.app`` directly.
"""

from __future__ import annotations

from .app import app, create_app
from .exceptions import DashboardError
from .news_agent_network_api import install_news_agent_network_api

install_news_agent_network_api(app)

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
