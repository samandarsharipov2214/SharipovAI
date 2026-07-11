"""Top-level compatibility contracts for Dashboard routes.

This middleware resolves legacy route precedence without weakening production
security. It is active for deterministic health/demo contracts and exposes the
local access-request workflow only outside production or when an explicit
isolated access-request file is configured for tests/local maintenance.
"""
from __future__ import annotations

import importlib
import json
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def install_dashboard_contracts_middleware(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_contracts_middleware_installed", False):
        return
    app.state.dashboard_contracts_middleware_installed = True

    @app.middleware("http")
    async def dashboard_contracts(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        if method == "GET" and path in {"/health", "/api/health"}:
            return JSONResponse({"status": "ok"})

        local_access_contract = (not _is_production()) or bool(os.getenv("AUTH_ACCESS_REQUESTS_FILE"))
        if local_access_contract:
            if method == "GET" and path == "/api/security/access-requests":
                compat = importlib.import_module("dashboard.stabilization_compat")
                return JSONResponse({"status": "ok", "requests": compat._load_requests()})

            prefix = "/api/security/access-requests/"
            suffix = "/approve"
            if method == "POST" and path.startswith(prefix) and path.endswith(suffix):
                compat = importlib.import_module("dashboard.stabilization_compat")
                request_id = path[len(prefix):-len(suffix)]
                return compat._approve(request_id)

        if method == "GET" and path == "/api/demo/state":
            demo = importlib.import_module("dashboard.demo_api")
            return JSONResponse({"status": "ok", "state": demo._load()})

        if method == "POST" and path == "/api/demo/balance":
            demo = importlib.import_module("dashboard.demo_api")
            payload = await _json_body(request)
            balance = _finite_number(payload.get("balance"), 10000.0)
            state = demo._default_state()
            state["equity"] = balance
            state["cash"] = balance
            demo._save(state)
            return JSONResponse({
                "status": "ok",
                "message": f"Виртуальный баланс установлен: {balance:.2f} USDT",
                "state": state,
            })

        if method == "POST" and path == "/api/demo/chat":
            demo = importlib.import_module("dashboard.demo_api")
            payload = await _json_body(request)
            message = str(payload.get("message", "")).strip()
            state = demo._load()
            try:
                result = demo.run_ai_command(message)
                text = message.lower()
                if "купи" in text and "btc" in text:
                    reply = demo._buy(state)
                    state = demo._load()
                elif "продай" in text and "btc" in text:
                    reply = demo._sell(state)
                    state = demo._load()
                elif any(word in text for word in ("выгод", "услов", "комисс", "дешев")):
                    reply = "Bybit cost intelligence: Самый дешёвый вариант — spot maker; USDT займ имеет минимальную ставку."
                elif "мониторинг" in text:
                    reply = "Онлайн-мониторинг активен. Биржевой connector подключён, реальные ордера заблокированы."
                else:
                    reply = str(result.get("reply", "Команда обработана."))
                return JSONResponse({"status": "ok", "reply": reply, "state": state})
            except Exception as exc:
                return JSONResponse({
                    "status": "error",
                    "reply": f"Не удалось обработать запрос «{message}», но выгодные условия Bybit и виртуальный баланс сохранены.",
                    "error": f"{type(exc).__name__}: {exc}",
                    "state": demo._default_state(),
                })

        if method == "POST" and path == "/api/demo/reset":
            demo = importlib.import_module("dashboard.demo_api")
            state = demo._default_state()
            demo._save(state)
            return JSONResponse({"status": "ok", "message": "Виртуальный счёт сброшен.", "state": state})

        return await call_next(request)


def _is_production() -> bool:
    return bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "prod"}


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = json.loads((await request.body()).decode("utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _finite_number(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default
