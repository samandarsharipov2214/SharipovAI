"""Dashboard package entrypoint for SharipovAI OS.

Render starts ``uvicorn dashboard:app``. Feature installers placed here must be
idempotent so Codex/tests may also import ``dashboard.app`` directly.
"""
from __future__ import annotations

from .app import app, create_app
from .admin_auth_compat import install_admin_auth_compat
from .lifecycle_compat import ensure_event_handler_compat
from .telegram_restore_compat import install_telegram_restore_compat

install_admin_auth_compat()
install_telegram_restore_compat()
# Rebind the package export after the compatibility installer wraps app.create_app.
from .app import create_app as create_app

ensure_event_handler_compat(app)

from .ai_organ_state_safe_api import install_ai_organ_state_api
from .autonomous_trading_api import install_autonomous_trading_api
from .bybit_account_api import install_bybit_account_api
from .campaign_api import install_campaign_api
from .control_plane_api import install_control_plane_api
from .currency_api import install_currency_api
from .dashboard2_api import install_dashboard2_api
from .database_api import install_database_api
from .exceptions import DashboardError
from .execution_stages_api import install_execution_stages_api
from .fill_harvester_api import install_fill_harvester_api
from .global_auth_guard import install_global_auth_guard
from .market_data_api import install_market_data_api
from .news_agent_network_api import install_news_agent_network_api
from .observability import install_observability
from .private_order_ws_api import install_private_order_ws_api
from .routers import install_operational_routers
from .source_status_compat_api import install_source_status_compat_api
from .system_health_api import install_system_health_api
from .system_watchdog import install_system_watchdog
from .web2_host import install_web2_host

install_database_api(app)
install_news_agent_network_api(app)
install_market_data_api(app)
install_autonomous_trading_api(app)
install_execution_stages_api(app)
install_bybit_account_api(app)
install_currency_api(app)
install_control_plane_api(app)
install_dashboard2_api(app)
install_private_order_ws_api(app)
install_fill_harvester_api(app)
install_campaign_api(app)
install_source_status_compat_api(app)
install_operational_routers(app)
install_web2_host(app)
install_global_auth_guard(app)
install_observability(app)
install_ai_organ_state_api(app)
install_system_health_api(app)
install_system_watchdog(app)

try:
    from .telegram_news_agents import install_telegram_news_agent_commands

    app.state.telegram_news_agent_commands = install_telegram_news_agent_commands()
except Exception as exc:
    app.state.telegram_news_agent_commands = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }

__all__: tuple[str, ...] = ("DashboardError", "app", "create_app")
