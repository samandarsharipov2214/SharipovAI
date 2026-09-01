"""Compatibility contracts for Telegram command/menu restoration.

The production menu remains the canonical SharipovAI Mini App.  The legacy
``_restore_commands_menu`` callable is retained for recovery tooling and tests;
it never changes webhook URLs or execution settings.

This installer binds the dashboard FastAPI app into ``telegram_system_adapter``
so Telegram reads ``telegram_runtime_state`` rather than demo sandbox state.
Missing runtime evidence is shown explicitly; financial values are never fabricated.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable

from telegram_runtime_state import canonical_state_from_app


def _state_loader() -> dict[str, Any]:
    """Resolve the already-created dashboard app lazily to avoid import cycles."""

    from .app import app

    return canonical_state_from_app(app)


def _install_canonical_state_views(adapter: Any) -> None:
    """Bind the dashboard app; adapter views already project canonical paper state."""

    from .app import app

    binder = getattr(adapter, "bind_runtime_app", None)
    if callable(binder):
        binder(app)
    adapter.TELEGRAM_STATE_SOURCE = "telegram_runtime_state"


def install_telegram_restore_compat() -> None:
    webhook_module = importlib.import_module("dashboard.telegram_webhook_api")
    adapter = importlib.import_module("telegram_system_adapter")
    _install_canonical_state_views(adapter)

    if not callable(getattr(webhook_module, "_restore_commands_menu", None)):

        def restore_commands_menu() -> dict[str, Any]:
            return webhook_module._telegram(
                "setChatMenuButton",
                {"menu_button": {"type": "commands"}},
            )

        webhook_module._restore_commands_menu = restore_commands_menu

    original_status: Callable[[], dict[str, Any]] = webhook_module._telegram_status

    if not getattr(original_status, "_canonical_state_wrapped", False):

        def canonical_telegram_status() -> dict[str, Any]:
            result = original_status()
            result["state_source"] = "autonomous_paper"
            result["deprecated_demo_state_used"] = False
            state = _state_loader()
            result["state_available"] = bool(state.get("data_available"))
            result["state_error"] = state.get("error")
            return result

        canonical_telegram_status._canonical_state_wrapped = True
        webhook_module._telegram_status = canonical_telegram_status


__all__ = [
    "_install_canonical_state_views",
    "_state_loader",
    "install_telegram_restore_compat",
]
