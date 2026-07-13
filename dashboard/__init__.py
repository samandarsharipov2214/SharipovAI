"""Dashboard package entrypoint for SharipovAI OS.

The canonical application is assembled here. Feature installers must be
idempotent so tests, Codex and the VPS process can import ``dashboard.app``
without creating duplicate routes or background workers.
"""
from __future__ import annotations

from .app import app, create_app
from .ai_organ_state_api import install_ai_organ_state_api
from .autonomous_trading_api import install_autonomous_trading_api
from .bybit_account_api import install_bybit_account_api
from .control_plane_api import install_control_plane_api
from .dashboard2_api import install_dashboard2_api
from .database_api import install_database_api
from .exceptions import DashboardError
from .execution_stages_api import install_execution_stages_api
from .global_auth_guard import install_global_auth_guard
from .lifecycle import install_fastapi_lifecycle_compat
from .market_data_api import install_market_data_api
from .news_agent_network_api import install_news_agent_network_api
from .private_order_ws_api import install_private_order_ws_api
from .system_health_api import install_system_health_api
from .system_watchdog import install_system_watchdog
from .web2_host import install_web2_host

# FastAPI 0.139+/Starlette 1.x may not expose app.add_event_handler. Install the
# narrow compatibility adapter before existing runtime modules register startup
# and shutdown handlers.
install_fastapi_lifecycle_compat(app)

# The canonical database must exist before any organ creates runtime state.
install_database_api(app)
install_news_agent_network_api(app)
install_market_data_api(app)
install_autonomous_trading_api(app)
install_execution_stages_api(app)
install_bybit_account_api(app)
install_control_plane_api(app)
install_dashboard2_api(app)
install_private_order_ws_api(app)
install_web2_host(app)
install_global_auth_guard(app)
# Monitoring is installed after the complete runtime graph and remains non-financial.
install_ai_organ_state_api(app)
install_system_health_api(app)
install_system_watchdog(app)

try:
    from .telegram_news_agents import install_telegram_news_agent_commands

    app.state.telegram_news_agent_commands = install_telegram_news_agent_commands()
except Exception as exc:  # adapter failure must not break dashboard startup
    app.state.telegram_news_agent_commands = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
