"""Dashboard package entrypoint for SharipovAI OS.

The VPS starts ``uvicorn dashboard:app``. Feature installers placed here must be
idempotent so tests, tools and the production process can import the same app
without creating duplicate routes or workers.
"""
from __future__ import annotations

from typing import Any

from .app import app, create_app as _create_base_app
from .lifecycle_compat import ensure_event_handler_compat
from .ai_organ_state_safe_api import install_ai_organ_state_api
from .autonomous_trading_api import install_autonomous_trading_api
from .bybit_account_api import install_bybit_account_api
from .control_plane_api import install_control_plane_api
from .dashboard2_api import install_dashboard2_api
from .database_api import install_database_api
from .exceptions import DashboardError
from .execution_stages_api import install_execution_stages_api
from .global_auth_guard import install_global_auth_guard
from .local_audit_api import install_local_audit_api
from .market_data_api import install_market_data_api
from .news_agent_network_api import install_news_agent_network_api
from .private_order_ws_api import install_private_order_ws_api
from .source_status_compat_api import install_source_status_compat_api
from .system_health_api import install_system_health_api
from .system_watchdog import install_system_watchdog
from .web2_host import install_web2_host


def create_app(runner_factory: Any | None = None):
    """Create a test/tool app that serves the same canonical Web2 shell."""
    instance = _create_base_app(runner_factory=runner_factory)
    ensure_event_handler_compat(instance)
    install_web2_host(instance)
    install_local_audit_api(instance)
    return instance


# FastAPI/Starlette runtime combinations may expose lifecycle registration only
# on ``app.router``. Install the compatibility method before feature installers.
ensure_event_handler_compat(app)

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
install_source_status_compat_api(app)
install_web2_host(app)
install_global_auth_guard(app)
# Monitoring is installed after the complete runtime graph and remains non-financial.
install_ai_organ_state_api(app)
install_system_health_api(app)
install_local_audit_api(app)
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
