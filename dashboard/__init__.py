"""Dashboard package entrypoint for SharipovAI OS.

Render starts ``uvicorn dashboard:app``. Feature installers placed here must be
idempotent so Codex/tests may also import ``dashboard.app`` directly.
"""

from __future__ import annotations

from .app import app, create_app
from .exceptions import DashboardError
from .market_data_api import install_market_data_api
from .news_agent_network_api import install_news_agent_network_api

install_news_agent_network_api(app)
install_market_data_api(app)

try:
    from .telegram_news_agents import install_telegram_news_agent_commands

    app.state.telegram_news_agent_commands = install_telegram_news_agent_commands()
except Exception as exc:  # adapter failure must not break dashboard startup
    app.state.telegram_news_agent_commands = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
