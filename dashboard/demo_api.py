"""Dashboard API endpoints for persistent demo trading."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from .demo_state import public_state, reset_state, run_ai_command, set_balance


def install_demo_api(app: FastAPI) -> None:
    """Install persistent demo account endpoints."""

    if getattr(app.state, "demo_api_installed", False):
        return
    app.state.demo_api_installed = True

    @app.get("/api/demo/state")
    def demo_state() -> dict[str, object]:
        """Return current persistent demo state."""

        try:
            return {"status": "ok", "state": public_state()}
        except Exception as exc:
            return {"status": "error", "error": _safe_error(exc), "state": _safe_state()}

    @app.post("/api/demo/chat")
    def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Run an AI-like command against the persistent demo account.

        This endpoint intentionally returns JSON even if the demo engine hits an
        internal problem, so the Mini App can show a useful answer instead of the
        generic "API недоступен" message.
        """

        message = str((payload or {}).get("message", ""))
        try:
            result = run_ai_command(message)
            return {"status": "ok", **result}
        except Exception as exc:
            return {
                "status": "error",
                "reply": _fallback_reply(message, exc),
                "error": _safe_error(exc),
                "state": _safe_state(),
            }

    @app.post("/api/demo/balance")
    def demo_balance(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Set demo balance and clear positions."""

        try:
            amount = (payload or {}).get("balance", 10_000.0)
            state = set_balance(float(amount))
            return {"status": "ok", "state": public_state(), "message": state.get("message", "Demo balance updated.")}
        except Exception as exc:
            return {"status": "error", "error": _safe_error(exc), "state": _safe_state()}

    @app.post("/api/demo/reset")
    def demo_reset(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Reset demo state."""

        try:
            amount = (payload or {}).get("balance", 10_000.0)
            state = reset_state(float(amount))
            return {"status": "ok", "state": public_state(), "message": state.get("message", "Demo account reset.")}
        except Exception as exc:
            return {"status": "error", "error": _safe_error(exc), "state": _safe_state()}


def _safe_state() -> dict[str, object]:
    """Return a minimal state for UI rendering when storage/calculation fails."""

    return {
        "mode": "DEMO",
        "currency": "USDT",
        "equity": 10_000.0,
        "cash": 10_000.0,
        "pnl": 0.0,
        "net_pnl": 0.0,
        "total_fees": 0.0,
        "commission_drag": 0.0,
        "risk_level": "LOW",
        "decision": "WATCH",
        "break_even_price": 50_000.0,
        "open_positions": 0,
        "positions": [],
        "trades": [],
        "exchange_status": {"mode": "sandbox", "can_execute_orders": False},
        "online_monitoring": {
            "demo_account_online": True,
            "cost_intelligence_online": False,
            "order_preview_online": False,
            "live_execution_enabled": False,
            "real_orders_blocked": True,
        },
    }


def _fallback_reply(message: str, exc: Exception) -> str:
    """Return a user-facing fallback reply for demo chat failures."""

    text = message.lower()
    if any(word in text for word in ("выгод", "услов", "комисс", "займ", "ставк", "vip", "дешев")):
        return (
            "Я понял запрос про выгодные условия Bybit, но backend cost intelligence ещё не поднялся на Render. "
            "После redeploy я буду сравнивать Spot/Futures/Options, maker/taker, VIP, займы и break-even. "
            "Реальные ордера не отправляю."
        )
    return "Демо-команда не выполнилась из-за внутренней ошибки backend. Подожди redeploy и попробуй ещё раз."


def _safe_error(exc: Exception) -> str:
    """Return a short non-secret error string."""

    return f"{type(exc).__name__}: {exc}"
