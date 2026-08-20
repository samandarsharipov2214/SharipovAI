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
    """Build the legacy integration factory while migration to the production graph is staged."""
    install_final_ci_contracts()
    instance = importlib.import_module("dashboard.app").create_app(*args, **kwargs)
    init_saas_database()
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
    if getattr(instance.state, "autonomous_paper_loop", None) is not None:
        install_canonical_runtime_compat_api(instance)
    install_security_headers(instance)
    return instance


def create_production_app(*args: Any, **kwargs: Any):
    """Build a fresh app with the same runtime graph as the production ``dashboard:app`` object."""
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


def _remove_route_owner(app: Any, *, method: str, path: str, module: str) -> None:
    """Remove one superseded compatibility owner before canonical installers run."""
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
            and getattr(getattr(route, "endpoint", None), "__module__", None) == module
        )
    ]


def _install_production_runtime_apis(app: Any) -> None:
    """Install the canonical production route/middleware graph on one app instance.

    The production global app and ``create_production_app`` share this installer
    graph. The historical ``create_app`` factory remains temporarily compatible
    with legacy tests until those contracts are migrated deliberately.
    """
    # The base factory still carries two migration-era owners. Keep them available
    # to legacy factories, but remove them from the canonical production graph so
    # request dispatch has exactly one owner for each method/path contract.
    _remove_route_owner(app, method="GET", path="/login", module="dashboard.demo_api")
    _remove_route_owner(app, method="GET", path="/api/auth/me", module="dashboard.app")

    install_database_api(app)
    install_news_agent_network_api(app)
    install_market_data_api(app)
    install_autonomous_trading_api(app)
    install_canonical_runtime_compat_api(app)
    install_execution_stages_api(app)
    install_bybit_account_api(app)
    install_currency_api(app)
    install_control_plane_api(app)
    install_dashboard2_api(app)
    install_private_order_ws_api(app)
    install_fill_harvester_api(app)
    install_campaign_api(app)
    install_phase7_campaign_api(app)
    install_phase8_campaign_api(app)
    install_phase9_campaign_api(app)
    install_phase10_scaling_api(app)
    install_self_learning_api(app)
    install_source_status_compat_api(app)
    install_operational_routers(app)
    install_web2_host(app)
    install_saas_auth_api(app)
    install_saas_billing_api(app)
    install_market_context_api(app)
    install_release_status_api(app)
    install_release_truth_api(app)
    install_release_truth_page(app)
    install_gemini_chat_api(app)
    install_internal_ai_code_fix_api(app)
    install_internal_agent_decisions_api(app)
    install_memory_api(app)
    install_global_auth_guard(app)
    install_security_headers(app)
    install_observability(app)
    install_ai_organ_state_api(app)
    install_system_health_api(app)
    install_system_watchdog(app)


_install_production_runtime_apis(app)

try:
    from .telegram_news_agents import install_telegram_news_agent_commands

    app.state.telegram_news_agent_commands = install_telegram_news_agent_commands()
except Exception as exc:
    app.state.telegram_news_agent_commands = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }

__all__ = ("DashboardError", "app", "create_app", "create_production_app")
