"""Final reload-safe dashboard contracts used by CI and production factories.

This module fixes route-precedence problems without weakening authentication:

* the configured administrator is authoritative over a persisted pending record;
* every newly created dashboard receives the contract middleware last, so stale
  compatibility middleware cannot fabricate Paper trades or shadow canonical APIs;
* legacy virtual trades without verified price/source evidence are quarantined,
  never upgraded with invented values;
* catch-up explicitly reports that historical prices were not fabricated.
"""
from __future__ import annotations

import hmac
import importlib
import os
from functools import wraps
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

_FACTORY_MARKER = "_sharipovai_final_ci_factory"
_APP_MARKER = "final_ci_contracts_installed"


def install_final_ci_contracts(app: FastAPI | None = None) -> None:
    """Patch reload-sensitive auth globals and finalize an application instance."""

    app_module = importlib.import_module("dashboard.app")
    _install_authoritative_auth(app_module)
    _wrap_app_factory(app_module)
    if app is not None:
        _install_app_middleware(app)


def _install_authoritative_auth(app_module: Any) -> None:
    """Install the canonical administrator-first functions on the current module."""

    compat = importlib.import_module("dashboard.admin_auth_compat")

    def valid_credentials(username: str, password: str) -> bool:
        current = importlib.import_module("dashboard.app")
        return bool(compat._valid_credentials(current, username, password))

    def session_username(request: Request) -> str | None:
        current = importlib.import_module("dashboard.app")
        return compat._session_username(current, request)

    app_module._valid_credentials = valid_credentials
    app_module._session_username = session_username
    app_module._final_ci_auth_installed = True

    # Modules imported before a dashboard.app reload may retain old function
    # objects. Rebind them when present; modules imported later receive the
    # current functions directly from dashboard.app.
    secure_module = _loaded_module("dashboard.secure_app")
    if secure_module is not None:
        secure_module._valid_credentials = valid_credentials
        secure_module._record_security_event = app_module._record_security_event

    admin_module = _loaded_module("dashboard.admin_secure_app")
    if admin_module is not None:
        admin_module._session_username = session_username
        admin_module._load_users = app_module._load_users
        admin_module._record_security_event = app_module._record_security_event

    stabilization = _loaded_module("dashboard.stabilization_compat")
    if stabilization is not None:
        _install_admin_login_override(stabilization, app_module)


def _wrap_app_factory(app_module: Any) -> None:
    current_factory = app_module.create_app
    if getattr(current_factory, _FACTORY_MARKER, False):
        return

    @wraps(current_factory)
    def create_app(*args: Any, **kwargs: Any) -> FastAPI:
        current = importlib.import_module("dashboard.app")
        _install_authoritative_auth(current)
        instance = current_factory(*args, **kwargs)
        _install_app_middleware(instance)
        return instance

    setattr(create_app, _FACTORY_MARKER, True)
    setattr(create_app, "__sharipovai_original__", current_factory)
    app_module.create_app = create_app


def _install_admin_login_override(stabilization: Any, app_module: Any) -> None:
    original = stabilization._login
    if getattr(original, "_sharipovai_admin_first", False):
        return

    @wraps(original)
    async def login(request: Request):
        form = parse_qs((await request.body()).decode("utf-8"))
        username = app_module._clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        admin_username = app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin"))
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        if (
            admin_password
            and username == admin_username
            and hmac.compare_digest(str(password), admin_password)
        ):
            next_url = app_module._safe_next_url((form.get("next") or ["/"])[0])
            response = RedirectResponse(next_url, status_code=303)
            response.set_cookie(
                app_module.SESSION_COOKIE,
                app_module._make_session(username),
                max_age=app_module.SESSION_TTL_SECONDS,
                httponly=True,
                secure=app_module._is_production(),
                samesite="lax",
                path="/",
            )
            return response
        return await original(request)

    login._sharipovai_admin_first = True
    stabilization._login = login


def _install_app_middleware(app: FastAPI) -> None:
    if getattr(app.state, _APP_MARKER, False):
        return
    setattr(app.state, _APP_MARKER, True)

    @app.middleware("http")
    async def final_ci_contracts(request: Request, call_next: Callable[..., Any]):
        path = request.url.path
        method = request.method.upper()

        if method == "POST" and path == "/login":
            admin_response = await _configured_admin_login(request)
            if admin_response is not None:
                return admin_response

        if method == "GET" and path == "/api/auth/role":
            return JSONResponse(_role_payload(request))

        if path in {
            "/api/paper-activity/state",
            "/api/virtual-account/state",
            "/api/paper-activity/trades",
            "/api/virtual-account/trades",
        } and method == "GET":
            return JSONResponse(_paper_read(path))

        if path in {"/api/paper-activity/tick", "/api/virtual-account/tick"} and method == "POST":
            return JSONResponse(await _paper_tick(request))

        if path in {"/api/paper-activity/catch-up", "/api/virtual-account/catch-up"} and method == "POST":
            return JSONResponse(await _paper_catch_up(request))

        return await call_next(request)


def _configured_admin_login(request: Request):
    async def resolve():
        app_module = importlib.import_module("dashboard.app")
        form = parse_qs((await request.body()).decode("utf-8"))
        username = app_module._clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        admin_username = app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin"))
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        if not (
            admin_password
            and username == admin_username
            and hmac.compare_digest(str(password), admin_password)
        ):
            return None
        next_url = app_module._safe_next_url((form.get("next") or ["/"])[0])
        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(
            app_module.SESSION_COOKIE,
            app_module._make_session(username),
            max_age=app_module.SESSION_TTL_SECONDS,
            httponly=True,
            secure=app_module._is_production(),
            samesite="lax",
            path="/",
        )
        app_module._record_security_event("login", username, request)
        return response

    return resolve()


def _role_payload(request: Request) -> dict[str, Any]:
    app_module = importlib.import_module("dashboard.app")
    username = app_module._session_username(request)
    if not username:
        return {"authenticated": False, "user": None, "role": None, "admin": False}

    admin_username = app_module._clean_username(os.getenv("ADMIN_USERNAME", "admin"))
    if username == admin_username and os.getenv("ADMIN_PASSWORD", ""):
        role = "admin"
    else:
        users = dict(app_module._load_users())
        try:
            stabilization = importlib.import_module("dashboard.stabilization_compat")
            users.update(stabilization._load_users())
        except Exception:
            pass
        record = users.get(app_module._clean_username(username))
        role = str(record.get("role", "user")) if isinstance(record, dict) else "user"

    return {
        "authenticated": True,
        "user": username,
        "role": role,
        "admin": role == "admin",
    }


def _paper_engine():
    module = importlib.import_module("market_paper_engine")
    engine = module.PaperActivityEngine()
    _quarantine_unverified_legacy_trades(engine)
    return engine


def _quarantine_unverified_legacy_trades(engine: Any) -> None:
    state = engine._load()
    trades = state.get("trades")
    if not isinstance(trades, list) or not trades:
        return

    valid: list[dict[str, Any]] = []
    quarantined = list(state.get("quarantined_trades") or [])
    changed = False
    for trade in trades:
        if not isinstance(trade, dict):
            changed = True
            continue
        try:
            entry_price = float(trade.get("entry_price", 0.0) or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        quote_source = str(
            trade.get("quote_source")
            or trade.get("last_quote_source")
            or ""
        ).strip()
        if (
            trade.get("real_order_placed") is False
            and entry_price > 0.0
            and quote_source
        ):
            valid.append(trade)
            continue
        changed = True
        quarantined.append(
            {
                **trade,
                "evidence_status": "quarantined_unverified_legacy_trade",
                "quarantine_reason": "positive verified entry price and quote source are required",
            }
        )

    if changed:
        state["trades"] = valid
        state["quarantined_trades"] = quarantined[-500:]
        state["quarantined_trade_count"] = len(quarantined)
        state["last_reason"] = "unverified_legacy_trades_quarantined"
        state["last_tick_status"] = "evidence_quarantine"
        engine._save(state)


def _canonical_state(*, catch_up: bool) -> dict[str, Any]:
    engine = _paper_engine()
    state = engine.state(catch_up=catch_up)
    explanations = importlib.import_module("dashboard.trade_explanations")
    state = explanations.enrich_virtual_state(state)
    state["real_orders_blocked"] = True
    state["historical_prices_fabricated"] = False
    state.setdefault("evidence_integrity", {})
    state["evidence_integrity"].update(
        {
            "legacy_unverified_trades_quarantined": True,
            "fabricated_prices": False,
        }
    )
    return state


def _paper_read(path: str) -> dict[str, Any]:
    state = _canonical_state(catch_up=path.endswith("/state"))
    if path.endswith("/trades"):
        return {
            "status": "ok",
            "summary": state.get("summary", {}),
            "trades": state.get("trades", []),
            "historical_prices_fabricated": False,
        }
    autorun = importlib.import_module("paper_activity_autorun")
    return {
        "status": "ok",
        "state": state,
        "autorun": autorun.paper_activity_autorun_status(),
        "historical_prices_fabricated": False,
    }


async def _paper_tick(request: Request) -> dict[str, Any]:
    payload = await _json_payload(request)
    engine = _paper_engine()
    result = engine.tick(
        force=bool(payload.get("force", False)),
        gate_payload=(
            payload.get("gate_payload")
            if isinstance(payload.get("gate_payload"), dict)
            else None
        ),
    )
    explanations = importlib.import_module("dashboard.trade_explanations")
    result = explanations.enrich_tick_result(result)
    result["historical_prices_fabricated"] = False
    if not isinstance(result.get("state"), dict):
        result["state"] = _canonical_state(catch_up=False)
    else:
        result["state"]["real_orders_blocked"] = True
        result["state"]["historical_prices_fabricated"] = False
    return result


async def _paper_catch_up(request: Request) -> dict[str, Any]:
    payload = await _json_payload(request)
    try:
        max_ticks = int(payload.get("max_ticks", 24) or 24)
    except (TypeError, ValueError):
        max_ticks = 24
    engine = _paper_engine()
    result = dict(engine.catch_up(max_ticks=max(1, min(max_ticks, 500))))
    result["historical_prices_fabricated"] = False
    result["state"] = _canonical_state(catch_up=False)
    return result


async def _json_payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _loaded_module(name: str) -> Any | None:
    import sys

    return sys.modules.get(name)


__all__ = ["install_final_ci_contracts"]
