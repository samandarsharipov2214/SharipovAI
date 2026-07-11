"""Backward-compatible Mini App endpoints.

The old ``/api/demo/*`` URLs remain so older JavaScript does not break, but
there is only one account state now: ``PaperActivityEngine`` / Virtual Account.
No separate demo balance is allowed to overwrite live virtual-account values.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from paper_activity_engine import PaperActivityEngine
from sharipovai_constitution import EXECUTION_MODE
from .demo_state import run_ai_command


def install_demo_api(app: FastAPI) -> None:
    """Install compatibility endpoints backed by the canonical virtual account."""

    if getattr(app.state, "demo_api_installed", False):
        return
    app.state.demo_api_installed = True

    @app.get("/api/demo/state")
    def demo_state() -> dict[str, object]:
        try:
            return {
                "status": "ok",
                "deprecated": True,
                "use": "/api/virtual-account/state",
                "state": _virtual_compat_state(catch_up=True),
            }
        except Exception as exc:
            return {"status": "error", "error": _safe_error(exc), "state": _safe_state()}

    @app.post("/api/demo/chat")
    def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Keep the legacy chat command but always return canonical account state."""

        message = str((payload or {}).get("message", ""))
        try:
            result = run_ai_command(message)
            return {
                "status": "ok",
                "deprecated": True,
                "use": "/api/virtual-account/state",
                "reply": result.get("reply", "Команда обработана."),
                "state": _virtual_compat_state(catch_up=True),
            }
        except Exception as exc:
            return {
                "status": "error",
                "reply": _fallback_reply(message, exc),
                "error": _safe_error(exc),
                "state": _safe_state(),
            }

    @app.post("/api/demo/balance")
    def demo_balance(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Reject a second balance source instead of silently diverging state."""

        requested = (payload or {}).get("balance")
        return {
            "status": "deprecated",
            "message": "Отдельный demo-баланс отключён. Используется единый Virtual Account.",
            "requested_balance": requested,
            "state": _virtual_compat_state(catch_up=True),
            "use": "/api/virtual-account/state",
        }

    @app.post("/api/demo/reset")
    def demo_reset(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Reset the canonical virtual account only when explicitly requested."""

        confirm = bool((payload or {}).get("confirm", False))
        if not confirm:
            return {
                "status": "confirmation_required",
                "message": "Для сброса единого Virtual Account передай confirm=true.",
                "state": _virtual_compat_state(catch_up=False),
            }
        result = PaperActivityEngine().reset()
        return {
            "status": "ok",
            "message": "Единый Virtual Account сброшен.",
            "state": _virtual_compat_state(catch_up=False),
            "result": result,
        }


def _virtual_compat_state(*, catch_up: bool) -> dict[str, object]:
    state = PaperActivityEngine().state(catch_up=catch_up)
    summary = state.get("summary", {}) if isinstance(state.get("summary"), dict) else {}
    equity = float(summary.get("equity", state.get("equity", 10000.0)) or 10000.0)
    cash = float(summary.get("cash", state.get("cash", equity)) or equity)
    net_pnl = float(summary.get("net_pnl", 0.0) or 0.0)
    total_fees = float(summary.get("total_fees", 0.0) or 0.0)
    return {
        **state,
        "mode": "VIRTUAL_ACCOUNT",
        "currency": "USDT",
        "equity": equity,
        "cash": cash,
        "pnl": net_pnl,
        "net_pnl": net_pnl,
        "total_fees": total_fees,
        "commission_drag": total_fees,
        "risk_level": "LOW" if summary.get("last_tick_status") != "blocked" else "HIGH",
        "decision": "WATCH" if summary.get("last_tick_status") in {"blocked", "wait_profitability", "not_started"} else "VIRTUAL",
        "open_positions": int(summary.get("open_positions", 0) or 0),
        "positions": [trade for trade in state.get("trades", []) if trade.get("status") == "OPEN"],
        "trades": list(state.get("trades", [])),
        "exchange_status": {"mode": "virtual_account", "can_execute_orders": False},
        "online_monitoring": {
            "virtual_account_online": True,
            "cost_intelligence_online": True,
            "order_preview_online": True,
            "live_execution_enabled": False,
            "real_orders_blocked": True,
        },
        "execution_mode": EXECUTION_MODE,
        "legacy_demo_endpoint": True,
    }


def _safe_state() -> dict[str, object]:
    try:
        return _virtual_compat_state(catch_up=False)
    except Exception:
        return {
            "mode": "VIRTUAL_ACCOUNT_ERROR",
            "currency": "USDT",
            "equity": 0.0,
            "cash": 0.0,
            "pnl": 0.0,
            "net_pnl": 0.0,
            "total_fees": 0.0,
            "open_positions": 0,
            "positions": [],
            "trades": [],
            "exchange_status": {"mode": "unavailable", "can_execute_orders": False},
            "online_monitoring": {"live_execution_enabled": False, "real_orders_blocked": True},
        }


def _fallback_reply(message: str, exc: Exception) -> str:
    text = message.lower()
    if any(word in text for word in ("выгод", "услов", "комисс", "займ", "ставк", "vip", "дешев")):
        return "Cost intelligence временно не ответил. Реальные ордера заблокированы; состояние Virtual Account сохранено."
    return "Команда не выполнилась, но единый Virtual Account не заменён статичными demo-данными."


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"
