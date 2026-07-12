"""Persistent paper-trading API shared by website, Mini App and Telegram."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ai_chat_orchestrator import answer_chat
from .dashboard_contracts_middleware import install_dashboard_contracts_middleware
from .stabilization_compat import install_stabilization_compat


def _path() -> Path:
    return Path(os.getenv("DEMO_STATE_FILE", "data/demo_state.json"))


def _default_state() -> dict[str, Any]:
    return {
        "mode": "PAPER",
        "equity": 10000.0,
        "cash": 10000.0,
        "pnl": 0.0,
        "net_pnl": 0.0,
        "total_fees": 0.0,
        "commission_drag": 0.0,
        "break_even_price": 0.0,
        "open_positions": 0,
        "positions": [],
        "trades": [],
        "exchange_status": {"mode": os.getenv("EXCHANGE_MODE", "sandbox"), "connected": True},
        "online_monitoring": {"demo_account_online": True, "exchange_connector_online": True, "real_orders_blocked": True, "live_execution_enabled": False},
        "bybit_costs": {"cheapest_product": "spot maker", "cheapest_borrow": "USDT займ"},
        "integration": {"website": True, "mini_app": True, "telegram": True, "source": "dashboard.demo_api"},
    }


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        state = _default_state()
        _save(state)
        return state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        base = _default_state()
        if isinstance(data, dict):
            base.update(data)
        base["integration"] = {"website": True, "mini_app": True, "telegram": True, "source": "dashboard.demo_api"}
        return base
    except Exception:
        return _default_state()


def _save(state: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _buy(state: dict[str, Any]) -> str:
    price = 60000.0
    notional = 1000.0
    fee_rate = float(os.getenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001"))
    fee = round(notional * fee_rate, 2)
    quantity = (notional - fee) / price
    break_even = round(price * (1 + 2 * fee_rate), 2)
    state["cash"] = round(float(state["cash"]) - notional, 2)
    state["open_positions"] = 1
    state["positions"] = [{"symbol": "BTCUSDT", "quantity": quantity, "entry_price": price, "entry_fee": fee}]
    state["trades"].append({"side": "BUY", "symbol": "BTCUSDT", "price": price, "quantity": quantity, "fee": fee, "break_even_price": break_even, "source": "shared_system"})
    state["total_fees"] = round(float(state.get("total_fees", 0)) + fee, 2)
    state["commission_drag"] = state["total_fees"]
    state["break_even_price"] = break_even
    state["equity"] = round(float(state["cash"]) + notional - fee, 2)
    _save(state)
    return f"SharipovAI купил BTC виртуально. Комиссия входа: {fee:.2f} USDT. Break-even: {break_even:.2f}."


def _sell(state: dict[str, Any]) -> str:
    fee_rate = float(os.getenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001"))
    position = (state.get("positions") or [{}])[0]
    entry_price = float(position.get("entry_price", 60000.0))
    quantity = float(position.get("quantity", 0.0))
    exit_price = entry_price
    gross = quantity * exit_price
    fee = round(gross * fee_rate, 2)
    entry_fee = float(position.get("entry_fee", 0.0))
    net_pnl = round(-entry_fee - fee, 2)
    state["cash"] = round(float(state["cash"]) + gross - fee, 2)
    state["open_positions"] = 0
    state["positions"] = []
    state["trades"].append({"side": "SELL", "symbol": "BTCUSDT", "price": exit_price, "quantity": quantity, "fee": fee, "net_pnl": net_pnl, "source": "shared_system"})
    state["total_fees"] = round(float(state.get("total_fees", 0)) + fee, 2)
    state["commission_drag"] = state["total_fees"]
    state["pnl"] = net_pnl
    state["net_pnl"] = net_pnl
    state["equity"] = state["cash"]
    _save(state)
    return f"BTC продан виртуально. net PnL после комиссий: {net_pnl:.2f} USDT."


def _chat(message: str) -> dict[str, Any]:
    state = _load()
    text = message.lower()
    if "купи" in text and "btc" in text:
        reply = _buy(state)
        state = _load()
        source_ai = "Paper Trading Bot + Risk Engine"
    elif "продай" in text and "btc" in text:
        reply = _sell(state)
        state = _load()
        source_ai = "Paper Trading Bot + Portfolio Engine"
    else:
        result = answer_chat(message, state)
        reply = str(result.get("reply", "Команда обработана."))
        source_ai = str(result.get("source_ai", "AI Chat Orchestrator"))
    return {"status": "ok", "reply": reply, "source_ai": source_ai, "state": state, "integration": state["integration"]}


def install_demo_api(app: FastAPI) -> None:
    install_dashboard_contracts_middleware(app)
    install_stabilization_compat(app)
    if getattr(app.state, "demo_api_installed", False):
        return
    app.state.demo_api_installed = True

    # This middleware deliberately supersedes legacy duplicate routes from
    # dashboard.routes. It guarantees one source of truth for all interfaces.
    @app.middleware("http")
    async def shared_demo_contract(request: Request, call_next):
        if request.url.path == "/api/demo/state" and request.method == "GET":
            return JSONResponse({"status": "ok", "state": _load()})
        if request.url.path == "/api/demo/chat" and request.method == "POST":
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            return JSONResponse(_chat(str((payload or {}).get("message", "")).strip()))
        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse)
    def compatibility_login_page() -> HTMLResponse:
        return HTMLResponse("""<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Вход в SharipovAI</title></head><body><main><h1>Вход в SharipovAI</h1><form method='post' action='/login'><input name='username' placeholder='Логин'><input name='password' type='password' placeholder='Пароль'><button type='submit'>Войти</button></form></main></body></html>""")

    @app.get("/api/demo/state/shared")
    def demo_state_shared() -> dict[str, object]:
        return {"status": "ok", "state": _load()}

    @app.post("/api/demo/balance")
    def demo_balance(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        balance = float((payload or {}).get("balance", 10000.0))
        state = _default_state()
        state["equity"] = balance
        state["cash"] = balance
        _save(state)
        return {"status": "ok", "message": f"Виртуальный баланс установлен: {balance:.2f} USDT", "state": state}

    @app.post("/api/demo/chat/shared")
    def demo_chat_shared(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        return _chat(str((payload or {}).get("message", "")).strip())

    @app.post("/api/demo/reset")
    def demo_reset(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        state = _default_state()
        _save(state)
        return {"status": "ok", "message": "Виртуальный счёт сброшен.", "state": state}
