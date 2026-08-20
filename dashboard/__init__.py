"""Dashboard package entrypoint for SharipovAI OS."""
from __future__ import annotations

import importlib
from typing import Any

from .app import app
from .admin_auth_compat import install_admin_auth_compat
from .auth_saas import install_saas_auth_api
from .billing_saas import install_saas_billing_api
from .db_saas import init_saas_database
from .final_ci_contracts import install_final_ci_contracts
from .lifecycle_compat import ensure_event_handler_compat
from .market_context_api import install_market_context_api
from .release_status_api import install_release_status_api
from .release_truth_api import install_release_truth_api
from .release_truth_page import install_release_truth_page
from .telegram_restore_compat import install_telegram_restore_compat

install_admin_auth_compat(force=True)
install_final_ci_contracts(app)
install_telegram_restore_compat()
ensure_event_handler_compat(app)
init_saas_database()


def create_app(*args: Any, **kwargs: Any):
    """Build the same application graph used by the production ``dashboard:app`` entrypoint."""
    install_final_ci_contracts()
    instance = importlib.import_module("dashboard.app").create_app(*args, **kwargs)
    init_saas_database()
    _install_production_runtime_apis(instance)
    return instance


from .ai_organ_state_safe_api import install_ai_organ_state_api
from .autonomous_trading_api import install_autonomous_trading_api
from .bybit_account_api import install_bybit_account_api
from .campaign_api import install_campaign_api
from .canonical_runtime_compat_api import install_canonical_runtime_compat_api
from .control_plane_api import install_control_plane_api
from .currency_api import install_currency_api
from .dashboard2_api import install_dashboard2_api
from .database_api import install_database_api
from .exceptions import DashboardError
from .execution_stages_api import install_execution_stages_api
from .fill_harvester_api import install_fill_harvester_api
from .gemini_chat_api import install_gemini_chat_api
from .global_auth_guard import install_global_auth_guard
from .internal_agent_decisions_api import install_internal_agent_decisions_api
from .internal_ai_code_fix_api import install_internal_ai_code_fix_api
from .market_data_api import install_market_data_api
from .memory_api import install_memory_api
from .news_agent_network_api import install_news_agent_network_api
from .observability import install_observability
from .phase7_campaign_api import install_phase7_campaign_api
from .phase8_campaign_api import install_phase8_campaign_api
from .phase9_campaign_api import install_phase9_campaign_api
from .phase10_scaling_api import install_phase10_scaling_api
from .private_order_ws_api import install_private_order_ws_api
from .routers import install_operational_routers
from .security_headers import install_security_headers
from .self_learning_api import install_self_learning_api
from .source_status_compat_api import install_source_status_compat_api
from .system_health_api import install_system_health_api
from .system_watchdog import install_system_watchdog
from .web2_host import install_web2_host


def _install_production_runtime_apis(instance: Any) -> None:
    """Install the canonical production route/middleware graph on one app instance.

    Keeping this list in one place prevents integration tests from exercising a
    smaller application than the ASGI object launched by ``uvicorn dashboard:app``.
    Individual installers remain responsible for their existing idempotency.
    """
    install_database_api(instance)
    install_news_agent_network_api(instance)
    install_market_data_api(instance)
    install_autonomous_trading_api(instance)
    install_canonical_runtime_compat_api(instance)
    install_execution_stages_api(instance)
    install_bybit_account_api(instance)
    install_currency_api(instance)
    install_control_plane_api(instance)
    install_dashboard2_api(instance)
    install_private_order_ws_api(instance)
    install_fill_harvester_api(instance)
    install_campaign_api(instance)
    install_phase7_campaign_api(instance)
    install_phase8_campaign_api(instance)
    install_phase9_campaign_api(instance)
    install_phase10_scaling_api(instance)
    install_self_learning_api(instance)
    install_source_status_compat_api(instance)
    install_operational_routers(instance)
    install_web2_host(instance)
    install_saas_auth_api(instance)
    install_saas_billing_api(instance)
    install_market_context_api(instance)
    install_release_status_api(instance)
    install_release_truth_api(instance)
    install_release_truth_page(instance)
    install_gemini_chat_api(instance)
    install_internal_ai_code_fix_api(instance)
    install_internal_agent_decisions_api(instance)
    install_memory_api(instance)
    install_global_auth_guard(instance)
    install_security_headers(instance)
    install_observability(instance)
    install_ai_organ_state_api(instance)
    install_system_health_api(instance)
    install_system_watchdog(instance)


_install_production_runtime_apis(app)

try:
    from .telegram_news_agents import install_telegram_news_agent_commands

    app.state.telegram_news_agent_commands = install_telegram_news_agent_commands()
except Exception as exc:
    app.state.telegram_news_agent_commands = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }

__all__ = ("DashboardError", "app", "create_app")
