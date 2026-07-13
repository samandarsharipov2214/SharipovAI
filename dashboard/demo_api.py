"""Deprecated read-only compatibility API for the canonical Virtual Account.

Legacy clients may still read ``/api/demo/*`` while migrating to
``/api/virtual-account/*``. This module never invents prices, creates trades, or
changes balances. All execution-like requests are blocked fail-closed.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

from ai_chat_orchestrator import answer_chat
from paper_activity_engine import PaperActivityEngine
from .canonical_contract_middleware import install_canonical_contract_middleware
from .dashboard_contracts_middleware import install_dashboard_contracts_middleware
from .route_cleanup import remove_legacy_routes, retain_last_registered_routes
from .stabilization_compat import install_stabilization_compat
from .web2_host import install_web2_host

_CANONICAL_STATE_ROUTE = "/api/virtual-account/state"
_CANONICAL_TICK_ROUTE = "/api/virtual-account/tick"
_DEMO_ROUTE_SPECS = (
    ("GET", "/api/demo/state"),
    ("POST", "/api/demo/chat"),
    ("POST", "/api/chat/message"),
)


def _canonical_state() -> dict[str, Any]:
    raw = PaperActivityEngine().state(catch_up=False)
    summary = raw.get("summary", {}) if isinstance(raw, dict) else {}
    trades = list(raw.get("trades", [])) if isinstance(raw, dict) and isinstance(raw.get("trades"), list) else []
    raw_positions = raw.get("positions", []) if isinstance(raw, dict) else []
    positions = list(raw_positions) if isinstance(raw_positions, list) else list(raw_positions.values()) if isinstance(raw_positions, dict) else []
    open_positions = int(summary.get("open_positions", len(positions)) or 0)
    equity = float(summary.get("equity", raw.get("equity", 10_000.0)) or 0.0)
    cash = float(summary.get("cash", raw.get("cash", equity)) or 0.0)
    net_pnl = float(summary.get("net_pnl", raw.get("net_pnl", 0.0)) or 0.0)
    total_fees = float(summary.get("total_fees", raw.get("total_fees", 0.0)) or 0.0)
    return {
        **(raw if isinstance(raw, dict) else {}),
        "mode": "VIRTUAL_ACCOUNT",
        "equity": equity,
        "cash": cash,
        "pnl": net_pnl,
        "net_pnl": net_pnl,
        "total_fees": total_fees,
        "commission_drag": total_fees,
        "open_positions": open_positions,
        "positions": positions,
        "trades": trades,
        "exchange_status": {
            "mode": os.getenv("EXCHANGE_MODE", "sandbox"),
            "connected": False,
            "verified": False,
            "reason": "legacy demo adapter has no exchange authority",
        },
        "online_monitoring": {
            "demo_account_online": True,
            "exchange_connector_online": False,
            "real_orders_blocked": True,
            "live_execution_enabled": False,
        },
        "bybit_costs": {
            "status": "not_verified_in_legacy_adapter",
            "source": "canonical market/exchange APIs required",
        },
        "integration": {
            "website": True,
            "mini_app": True,
            "telegram": True,
            "source": "canonical_virtual_account",
        },
        "synthetic_prices_used": False,
        "legacy_execution_enabled": False,
    }


def load_shared_state() -> dict[str, Any]:
    """Public read-only state accessor shared by Website, Telegram and Mini App."""

    return _canonical_state()


def _load() -> dict[str, Any]:
    """Backward-compatible alias; returns canonical state only."""

    return load_shared_state()


def _state_response() -> dict[str, Any]:
    return {
        "status": "ok",
        "deprecated": True,
        "use": _CANONICAL_STATE_ROUTE,
        "state": load_shared_state(),
    }


def run_ai_command(message: str) -> dict[str, Any]:
    """Run informational chat against the read-only canonical state."""

    return answer_chat(message, load_shared_state())


def _is_execution_request(message: str) -> bool:
    text = message.casefold()
    execution_words = ("купи", "купить", "buy", "продай", "продать", "sell")
    return "btc" in text and any(word in text for word in execution_words)


def _chat(message: str) -> dict[str, Any]:
    state = load_shared_state()
    if _is_execution_request(message):
        return {
            "status": "blocked",
            "reply": (
                "Legacy Demo execution отключён: выдуманные цены и сделки запрещены. "
                f"Используйте канонический Virtual Account через {_CANONICAL_TICK_ROUTE}; "
                "новый вход требует Decision Quality, General Controller и Risk evidence."
            ),
            "source_ai": "Security Guard + Virtual Execution",
            "state": state,
            "deprecated": True,
            "use": _CANONICAL_TICK_ROUTE,
            "real_orders_blocked": True,
        }
    try:
        result = run_ai_command(message)
    except Exception as exc:
        return {
            "status": "error",
            "reply": f"Не удалось обработать запрос «{message}»: {type(exc).__name__}.",
            "source_ai": "AI Chat Orchestrator",
            "state": state,
            "deprecated": True,
            "use": _CANONICAL_STATE_ROUTE,
        }
    return {
        "status": "ok",
        "reply": str(result.get("reply", "Команда обработана.")),
        "source_ai": str(result.get("source_ai", "AI Chat Orchestrator")),
        "state": state,
        "integration": state["integration"],
        "deprecated": True,
        "use": _CANONICAL_STATE_ROUTE,
    }


def _blocked_write(action: str) -> JSONResponse:
    return JSONResponse(
        {
            "status": "blocked",
            "detail": f"Legacy demo {action} is disabled",
            "deprecated": True,
            "use": _CANONICAL_STATE_ROUTE,
            "real_orders_blocked": True,
        },
        status_code=409,
    )


def install_demo_api(app: FastAPI) -> None:
    install_web2_host(app)
    install_dashboard_contracts_middleware(app)
    install_stabilization_compat(app)
    install_canonical_contract_middleware(app)
    if getattr(app.state, "demo_api_installed", False):
        return
    app.state.demo_api_installed = True

    remove_legacy_routes(
        app,
        (*_DEMO_ROUTE_SPECS, ("GET", "/api/social-news"), ("POST", "/api/social-news/rss/refresh")),
    )

    @app.get("/api/demo/state")
    def demo_state() -> dict[str, Any]:
        return _state_response()

    @app.post("/api/demo/chat")
    def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        return _chat(str((payload or {}).get("message", "")).strip())

    @app.post("/api/chat/message")
    def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        result = _chat(str((payload or {}).get("message", "")).strip())
        return {**result, "run": {"status": result["status"], "mode": "canonical_virtual_account"}}

    @app.get("/api/demo/state/shared")
    def demo_state_shared() -> dict[str, Any]:
        return _state_response()

    @app.post("/api/demo/balance")
    def demo_balance(_payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        return _blocked_write("balance mutation")

    @app.post("/api/demo/chat/shared")
    def demo_chat_shared(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        return _chat(str((payload or {}).get("message", "")).strip())

    @app.post("/api/demo/reset")
    def demo_reset(_payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        return _blocked_write("reset")

    retain_last_registered_routes(app, _DEMO_ROUTE_SPECS)


__all__ = ["install_demo_api", "load_shared_state", "run_ai_command"]
