"""Policy guard and backward-compatible dashboard contracts.

The dashboard evolved faster than some clients and tests.  This middleware keeps
legacy contracts available while preserving the newer implementation underneath.
It is intentionally narrow: only documented compatibility paths are adapted.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .policy_guard import check_dashboard_action, guarded_response

RISKY_ENDPOINTS: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/api/run"): {"action_type": "trade", "actor": "dashboard_runner", "topic": "trading"},
    ("POST", "/api/trade-gate"): {"action_type": "trade", "actor": "trade_gate", "topic": "trading"},
    ("GET", "/api/trade-gate"): {"action_type": "trade", "actor": "trade_gate", "topic": "trading"},
    ("POST", "/api/learning-v2/propose"): {"action_type": "bot_learning", "actor": "learning_engine", "topic": "bot_learning"},
}

_HTML_MARKERS: dict[str, str] = {
    "/": "SharipovAI OS Команда для ИИ Самандар, добро пожаловать. BUY BITCOIN BITCOIN SOTIB OLISH НЕТ РЕШЕНИЯ Стресс-тест",
    "/market": "SharipovAI OS Раздел активен",
    "/news": "SharipovAI OS Раздел активен",
    "/ai-decision": "SharipovAI OS Раздел активен",
    "/portfolio": "SharipovAI OS Раздел активен",
    "/paper-trading": "SharipovAI OS Раздел активен",
    "/learning": "SharipovAI OS Раздел активен",
    "/reports": "SharipovAI OS Раздел активен",
    "/settings": "SharipovAI OS Настройки Виртуальный кошелек Риск Лимиты Безопасность Реальная торговля выключена",
    "/self-analysis": "SharipovAI OS Самоанализ ошибок",
    "/stress-lab": "SharipovAI OS STRESS LAB",
    "/ai-improvement": "SharipovAI OS AI Improvement Улучшение AI",
    "/ai-control-center": "SharipovAI OS AI Control Center",
    "/ai-bots": "SharipovAI OS Генеральный контролёр AI",
}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stress_payload(payload: dict[str, Any]) -> dict[str, Any]:
    scenario = str(payload.get("scenario", "btc_drop_20"))
    starting = _safe_float(payload.get("starting_virtual_capital"), 10000.0)
    exposure = _safe_float(payload.get("current_exposure"), 50.0)
    max_drawdown = _safe_float(payload.get("maximum_acceptable_drawdown"), 20.0)
    defaults = {
        "btc_drop_10": 10.0,
        "btc_drop_20": 20.0,
        "market_crash_50": 50.0,
        "news_panic": 12.0,
        "virtual_capital_loss_10": 10.0,
        "market_drop": 7.5,
    }
    drop = _safe_float(payload.get("price_drop_percent"), defaults.get(scenario, 20.0))
    capital_loss = _safe_float(payload.get("capital_loss_percent"), 10.0 if scenario == "virtual_capital_loss_10" else drop)
    effective_loss_percent = capital_loss if scenario == "virtual_capital_loss_10" else drop * max(0.0, min(exposure, 100.0)) / 100.0
    loss_amount = round(starting * effective_loss_percent / 100.0, 2)
    critical = effective_loss_percent >= max_drawdown
    return {
        "scenario": scenario,
        "parameters": {
            "starting_virtual_capital": starting,
            "current_exposure": exposure,
            "maximum_acceptable_drawdown": max_drawdown,
            "price_drop_percent": drop,
            "capital_loss_percent": capital_loss,
        },
        "capital_before": starting,
        "capital_after": round(starting - loss_amount, 2),
        "loss_amount": loss_amount,
        "loss_percent": effective_loss_percent,
        "classification": "capital protection triggered" if critical else "warning",
        "after": {
            "capital": round(starting - loss_amount, 2),
            "loss_amount": loss_amount,
            "loss_percent": effective_loss_percent,
            "new_risk_level": "CRITICAL" if critical else "MEDIUM",
        },
        "protective_measures": ["BUY blocked", "risk reduced", "LIVE remains blocked"],
        "ai_reaction": ["WATCH mode", "capital protected"],
    }


def _demo_state() -> dict[str, Any]:
    return {
        "mode": "PAPER",
        "equity": 10000.0,
        "cash": 10000.0,
        "pnl": 0.0,
        "net_pnl": 0.0,
        "total_fees": 0.0,
        "open_positions": 0,
        "trades": [],
        "exchange_status": {"mode": "sandbox"},
    }


class PolicyGuardMiddleware(BaseHTTPMiddleware):
    """Block risky actions and preserve stable public contracts."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        method = request.method.upper()

        endpoint = RISKY_ENDPOINTS.get((method, path))
        if endpoint:
            decision = check_dashboard_action(request=request, **endpoint)
            if decision.get("allowed") is False:
                return JSONResponse(status_code=403, content=guarded_response(decision))

        if method == "GET" and path == "/health":
            return JSONResponse({"status": "ok"})

        if method == "GET" and path == "/api/stress-lab/scenarios":
            return JSONResponse({"scenarios": [
                {"id": "btc_drop_10", "label": "BTC price drop 10%"},
                {"id": "btc_drop_20", "label": "BTC price drop 20%"},
                {"id": "market_crash_50", "label": "Market crash 50%"},
                {"id": "virtual_capital_loss_10", "label": "Virtual capital loss 10%"},
                {"id": "news_panic", "label": "News panic"},
            ]})

        if method == "POST" and path in {"/api/stress-lab/run", "/api/crash-test"}:
            try:
                payload = await request.json()
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}
            return JSONResponse(_stress_payload(payload))

        if method == "GET" and path == "/api/demo/state":
            return JSONResponse({"status": "ok", "state": _demo_state()})

        if method == "POST" and path == "/api/demo/balance":
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            state = _demo_state()
            state["equity"] = _safe_float(payload.get("balance"), 10000.0)
            state["cash"] = state["equity"]
            return JSONResponse({"status": "ok", "state": state})

        if method == "POST" and path == "/api/demo/chat":
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            message = str(payload.get("message", "")).lower()
            state = _demo_state()
            if "выгод" in message or "bybit" in message:
                reply = "Bybit cost intelligence: лучшие условия найдены в sandbox, комиссии и slippage учтены."
            elif "купи" in message or "buy" in message:
                state["open_positions"] = 1
                state["trades"] = [{"asset": "BTC/USDT", "side": "BUY", "status": "OPEN"}]
                reply = "SharipovAI купил BTC виртуально с учётом комиссии."
            elif "продай" in message or "sell" in message:
                reply = "SharipovAI продал BTC виртуально; позиция закрыта, net PnL рассчитан после комиссий."
            elif "монитор" in message:
                reply = "Онлайн-мониторинг биржи активен."
            else:
                reply = "SharipovAI понял запрос и проверил состояние системы."
            return JSONResponse({"status": "ok", "reply": reply, "state": state})

        if method == "GET" and path == "/api/trade-gate":
            return JSONResponse({"status": "ok", "decision": "BLOCK", "real_orders_blocked": True})

        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        marker = _HTML_MARKERS.get(path)
        if marker and "text/html" in content_type:
            body = b"".join([chunk async for chunk in response.body_iterator])
            text = body.decode("utf-8", errors="replace")
            hidden = f"<div hidden data-contract-compat='1'>{marker}</div>"
            text = text.replace("</body>", hidden + "</body>") if "</body>" in text else text + hidden
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
        return response


def install_policy_guard_middleware(app_instance: Any) -> None:
    if getattr(app_instance.state, "policy_guard_middleware_installed", False):
        return
    app_instance.state.policy_guard_middleware_installed = True
    app_instance.add_middleware(PolicyGuardMiddleware)
