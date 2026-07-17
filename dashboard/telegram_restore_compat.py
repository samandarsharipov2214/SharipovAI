"""Compatibility contracts for Telegram command/menu restoration.

The production menu remains the canonical SharipovAI Mini App.  The legacy
``_restore_commands_menu`` callable is retained for recovery tooling and tests;
it never changes webhook URLs or execution settings.
"""
from __future__ import annotations

import importlib
from typing import Any


def install_telegram_restore_compat() -> None:
    module = importlib.import_module("dashboard.telegram_webhook_api")
    if callable(getattr(module, "_restore_commands_menu", None)):
        return

    def restore_commands_menu() -> dict[str, Any]:
        return module._telegram(
            "setChatMenuButton",
            {"menu_button": {"type": "commands"}},
        )

    module._restore_commands_menu = restore_commands_menu


__all__ = ["install_telegram_restore_compat"]
