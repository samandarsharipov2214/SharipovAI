"""Compatibility contracts for Telegram command/menu restoration.

The production menu remains the canonical SharipovAI Mini App.  The legacy
``_restore_commands_menu`` callable is retained for recovery tooling and tests;
it never changes webhook URLs or execution settings.

This installer also replaces the historical ``demo_state.json`` Telegram view
with a read-only projection of the canonical autonomous-paper runtime.  Missing
runtime evidence is shown explicitly; financial values are never fabricated.
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
    adapter.load_shared_state = _state_loader

    def overview() -> str:
        state = _state_loader()
        if not state.get("data_available"):
            reason = adapter._safe(state.get("error", "canonical runtime unavailable"))
            return (
                "⚠️ <b>Канонический runtime недоступен</b>\n\n"
                "Telegram не показывает резервный demo-баланс и не выдумывает PnL.\n"
                f"Причина: <code>{reason}</code>"
            )

        worker = "работает" if state.get("worker_running") else "остановлен"
        database = "подключена" if state.get("database_backed") else "не подтверждена"
        market = "проверен" if state.get("market_verified") else "не подтверждён"
        return (
            "🏠 <b>SharipovAI Mission Control</b>\n\n"
            f"Источник: <b>{adapter._safe(state.get('source_of_truth'))}</b>\n"
            f"Режим: <b>{adapter._safe(state.get('mode'))}</b>\n"
            f"Equity: <b>{float(state.get('equity') or 0):.2f} USDT</b>\n"
            f"Cash: <b>{float(state.get('cash') or 0):.2f} USDT</b>\n"
            f"Net PnL: <b>{float(state.get('net_pnl') or 0):.2f} USDT</b>\n"
            f"Комиссии: <b>{float(state.get('total_fees') or 0):.2f} USDT</b>\n"
            f"Открытые позиции: <b>{int(state.get('open_positions') or 0)}</b>\n"
            f"Всего сделок: <b>{int(state.get('trade_count') or 0)}</b>\n"
            f"Worker: <b>{worker}</b>\n"
            f"База данных: <b>{database}</b>\n"
            f"Рыночные данные: <b>{market}</b>"
        )

    def trades() -> str:
        state = _state_loader()
        if not state.get("data_available"):
            reason = adapter._safe(state.get("error", "canonical runtime unavailable"))
            return (
                "⚠️ <b>Сделки недоступны</b>\n\n"
                "Deprecated demo-журнал не используется.\n"
                f"Причина: <code>{reason}</code>"
            )

        items = list(state.get("trades") or [])
        total = int(state.get("trade_count") or len(items))
        lines = [
            "💼 <b>Канонические сделки</b>",
            f"Источник: <b>{adapter._safe(state.get('source_of_truth'))}</b>",
            f"Всего в базе: <b>{total}</b>",
            "",
        ]
        if not items:
            lines.append("Подтверждённых сделок пока нет.")
        for index, trade in enumerate(items[-10:], start=max(1, total - len(items[-10:]) + 1)):
            symbol = adapter._safe(trade.get("symbol", "UNKNOWN"))
            side = adapter._safe(trade.get("side", ""))
            fee = adapter._safe(trade.get("fee", 0))
            net_pnl = adapter._safe(trade.get("net_pnl", "—"))
            reason = adapter._safe(trade.get("reason", "—"))
            lines.append(
                f"{index}. <b>{symbol}</b> {side} · fee {fee} · net PnL {net_pnl} · {reason}"
            )
        return "\n".join(lines)

    def status() -> str:
        state = _state_loader()
        if not state.get("data_available"):
            reason = adapter._safe(state.get("error", "canonical runtime unavailable"))
            return (
                "📡 <b>Статус интеграции</b>\n\n"
                "Canonical autonomous runtime: <b>недоступен</b>\n"
                "Demo fallback: <b>запрещён</b>\n"
                f"Причина: <code>{reason}</code>\n"
                "LIVE execution: <b>заблокирован</b>"
            )

        return (
            "📡 <b>Статус интеграции</b>\n\n"
            "Website core: <b>подключён</b>\n"
            "Telegram state source: <b>autonomous_paper</b>\n"
            f"Worker: <b>{'работает' if state.get('worker_running') else 'остановлен'}</b>\n"
            f"ProjectDatabase: <b>{'подключена' if state.get('database_backed') else 'не подтверждена'}</b>\n"
            f"Verified market stream: <b>{'да' if state.get('market_verified') else 'нет'}</b>\n"
            "Deprecated demo state: <b>не используется</b>\n"
            f"Mini App: <b>{adapter._safe(adapter._webapp_url())}</b>\n"
            "LIVE execution: <b>заблокирован</b>"
        )

    adapter._overview = overview
    adapter._trades = trades
    adapter._status = status
    adapter.TELEGRAM_STATE_SOURCE = "autonomous_paper"


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
