"""Dashboard package entrypoint for SharipovAI OS.

Render starts ``uvicorn dashboard:app``. Feature installers placed here must be
idempotent so Codex/tests may also import ``dashboard.app`` directly.
"""
from __future__ import annotations

from .app import app, create_app
from .autonomous_trading_api import install_autonomous_trading_api
from .bybit_account_api import install_bybit_account_api
from .control_plane_api import install_control_plane_api
from .dashboard2_api import install_dashboard2_api
from .database_api import install_database_api
from .exceptions import DashboardError
from .execution_stages_api import install_execution_stages_api
from .global_auth_guard import install_global_auth_guard
from .market_data_api import install_market_data_api
from .news_agent_network_api import install_news_agent_network_api
from .private_order_ws_api import install_private_order_ws_api
from .system_health_api import install_system_health_api
from .web2_host import install_web2_host

install_news_agent_network_api(app)
install_market_data_api(app)
install_autonomous_trading_api(app)
install_execution_stages_api(app)
install_bybit_account_api(app)
install_control_plane_api(app)
install_dashboard2_api(app)
install_database_api(app)
install_private_order_ws_api(app)
install_web2_host(app)
install_global_auth_guard(app)
install_system_health_api(app)

try:
    from .telegram_news_agents import install_telegram_news_agent_commands

    app.state.telegram_news_agent_commands = install_telegram_news_agent_commands()
except Exception as exc:  # adapter failure must not break dashboard startup
    app.state.telegram_news_agent_commands = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
