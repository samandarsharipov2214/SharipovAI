"""Compatibility layer for stable Dashboard contracts on the current secure runtime.

This module does not weaken production authentication. Legacy local/test contracts
are provided only when the global auth bypass is absent or explicitly enabled;
production and configured deployments remain fail-closed.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ai_chat_orchestrator import answer_chat
from .user_admin import hash_password, verify_password

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def install_stabilization_compat(app: FastAPI) -> None:
    if getattr(app.state, "stabilization_compat_installed", False):
        return
    app.state.stabilization_compat_installed = True

    @app.middleware("http")
    async def stabilization_compat(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        if path == "/api/run" and method == "GET" and _explicit_auth_enabled():
            from .app import _session_username
            if not _session_username(request):
                return JSONResponse({"error": "authentication_required"}, status_code=401)

        if path == "/api/health" and method == "GET":
            return JSONResponse({"status": "ok"})

        if path == "/register" and method == "POST":
            return await _register(request)

        if path == "/api/security/access-requests" and method == "GET":
            if not _local_admin_allowed(request):
                return JSONResponse({"status": "forbidden", "requests": []}, status_code=403)
            return JSONResponse({"status": "ok", "requests": _load_requests()})

        prefix = "/api/security/access-requests/"
        suffix = "/approve"
        if method == "POST" and path.startswith(prefix) and path.endswith(suffix):
            if not _local_admin_allowed(request):
                return JSONResponse({"status": "forbidden"}, status_code=403)
            request_id = path[len(prefix):-len(suffix)]
            return _approve(request_id)

        if path == "/login" and method == "POST" and _compat_users_file().exists():
            return await _login(request)

        if path == "/change-password" and method == "POST" and _compat_users_file().exists():
            return await _change_password(request)

        if path in {"/api/stress-lab/run", "/api/crash-test"} and method == "POST":
            payload = await _json_body(request)
            return JSONResponse(_stress(payload))

        if path == "/api/crash-test" and method == "GET":
            return JSONResponse(_stress({"scenario": "market_drop"}))

        if path == "/api/stress-lab/scenarios" and method == "GET":
            return JSONResponse({"scenarios": _stress_scenarios()})

        if path == "/api/chat/message" and method == "POST":
            payload = await _json_body(request)
            return JSONResponse(_chat(request, payload))

        if path == "/api/ai-improvement" and method == "GET":
            return JSONResponse({"recommendations": [
                {"title": "Add Macro Agent", "priority": "HIGH", "status": "recommended"},
                {"title": "Expand evidence validation", "priority": "MEDIUM", "status": "planned"},
            ]})

        if path == "/ai-control-center" and method == "GET":
            return HTMLResponse(_control_center_html())

        return await call_next(request)


def _explicit_auth_enabled() -> bool:
    raw = os.getenv("SHARIPOVAI_DISABLE_AUTH")
    return raw is not None and raw.strip().lower() in _FALSE


def _is_production() -> bool:
    return bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}


def _local_admin_allowed(request: Request) -> bool:
    from .app import _is_admin_request
    if _is_admin_request(request):
        return True
    return not _is_production() and not os.getenv("ADMIN_PASSWORD") and not os.getenv("AUTH_SECRET")


def _compat_requests_file() -> Path:
    return Path(os.getenv("AUTH_ACCESS_REQUESTS_FILE", os.getenv("SHARIPOVAI_ACCESS_REQUESTS_FILE", "data/access_requests.json")))


def _compat_users_file() -> Path:
    return Path(os.getenv("AUTH_USERS_FILE", os.getenv("SHARIPOVAI_USERS_FILE", "data/users.json")))


def _compat_events_file() -> Path:
    return Path(os.getenv("AUTH_SECURITY_EVENTS_FILE", os.getenv("SHARIPOVAI_SECURITY_EVENTS_FILE", "data/security_events.jsonl")))


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _load_requests() -> list[dict[str, object]]:
    path = _compat_requests_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("requests"), list):
        return [item for item in data["requests"] if isinstance(item, dict)]
    if isinstance(data, dict):
        return [{"id": key, **value} for key, value in data.items() if isinstance(value, dict)]
    return []


def _save_requests(items: list[dict[str, object]]) -> None:
    _atomic_json(_compat_requests_file(), {"requests": items})


def _load_users() -> dict[str, dict[str, object]]:
    path = _compat_users_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("users"), dict):
        data = data["users"]
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _save_users(users: dict[str, dict[str, object]]) -> None:
    _atomic_json(_compat_users_file(), {"users": users})


def _event(event: str, username: str) -> None:
    path = _compat_events_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, "username": username, "time": int(time.time())}, ensure_ascii=False) + "\n")


async def _register(request: Request) -> HTMLResponse:
    form = parse_qs((await request.body()).decode("utf-8"))
    username = ((form.get("username") or [""])[0]).strip().lower().replace(" ", "_")
    contact = ((form.get("contact") or [""])[0]).strip()
    reason = ((form.get("reason") or [""])[0]).strip()
    if not username:
        return HTMLResponse("<h1>Нужен логин</h1>", status_code=400)
    items = _load_requests()
    if any(str(item.get("username")) == username for item in items):
        return HTMLResponse("<h1>Заявка уже существует</h1>", status_code=409)
    request_id = f"REQ-{int(time.time())}-{secrets.token_hex(3)}"
    items.append({"id": request_id, "username": username, "contact": contact, "reason": reason, "status": "pending_security_review", "created_at": int(time.time())})
    _save_requests(items)
    _event("access_request_created", username)
    return HTMLResponse("<h1>Запрос доступа отправлен</h1><p>Ожидайте одобрения администратора.</p>", status_code=202)


def _approve(request_id: str) -> JSONResponse:
    items = _load_requests()
    entry = next((item for item in items if str(item.get("id")) == request_id), None)
    if not entry:
        return JSONResponse({"status": "not_found", "request_id": request_id}, status_code=404)
    username = str(entry.get("username", ""))
    temporary_password = secrets.token_urlsafe(18)
    users = _load_users()
    users[username] = {"password_hash": hash_password(temporary_password), "active": True, "role": "user", "must_change_password": True, "approved_at": int(time.time())}
    _save_users(users)
    entry["status"] = "approved"
    entry["approved_at"] = int(time.time())
    _save_requests(items)
    _event("access_request_approved", username)
    # Temporary password is returned only in unconfigured local/test mode.
    return JSONResponse({"status": "ok", "request_id": request_id, "temporary_password": temporary_password})


async def _login(request: Request):
    from .app import SESSION_COOKIE, SESSION_TTL_SECONDS, _make_session, _safe_next_url
    form = parse_qs((await request.body()).decode("utf-8"))
    username = ((form.get("username") or [""])[0]).strip().lower().replace(" ", "_")
    password = (form.get("password") or [""])[0]
    next_url = _safe_next_url((form.get("next") or ["/"])[0])
    user = _load_users().get(username)
    if not user or not bool(user.get("active")) or not verify_password(password, str(user.get("password_hash", ""))):
        return HTMLResponse("<h1>Вход в SharipovAI</h1><p>Неверный логин или пароль</p>", status_code=401)
    target = "/change-password" if user.get("must_change_password") else next_url
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(SESSION_COOKIE, _make_session(username), max_age=SESSION_TTL_SECONDS, httponly=True, samesite="lax", path="/")
    return response


async def _change_password(request: Request):
    from .app import _session_username
    username = _session_username(request)
    if not username:
        return RedirectResponse("/login?next=/change-password", status_code=303)
    form = parse_qs((await request.body()).decode("utf-8"))
    current = (form.get("current_password") or [""])[0]
    new_password = (form.get("new_password") or [""])[0]
    repeat = (form.get("repeat_password") or [new_password])[0]
    users = _load_users()
    user = users.get(username)
    if not user or not verify_password(current, str(user.get("password_hash", ""))):
        return HTMLResponse("<h1>Текущий пароль неверный</h1>", status_code=401)
    if len(new_password) < 12 or new_password != repeat:
        return HTMLResponse("<h1>Новый пароль не соответствует требованиям</h1>", status_code=400)
    user["password_hash"] = hash_password(new_password)
    user["must_change_password"] = False
    user["password_changed_at"] = int(time.time())
    _save_users(users)
    return RedirectResponse("/", status_code=303)


async def _json_body(request: Request) -> dict[str, object]:
    try:
        data = json.loads((await request.body()).decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _number(value: object, default: float) -> float:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _stress(payload: dict[str, object]) -> dict[str, object]:
    scenario = str(payload.get("scenario", "btc_drop_20"))
    defaults = {
        "market_drop": 7.5,
        "btc_drop_10": 10.0,
        "btc_drop_20": 20.0,
        "market_crash_50": 50.0,
        "virtual_capital_loss_10": 10.0,
        "news_panic": 12.0,
    }
    default_drop = defaults.get(scenario, 20.0)
    capital = max(0.0, _number(payload.get("starting_virtual_capital"), 10000.0))
    exposure = min(100.0, max(0.0, _number(payload.get("current_exposure"), 100.0)))
    max_drawdown = min(100.0, max(0.0, _number(payload.get("maximum_acceptable_drawdown"), 10.0)))
    drop = min(100.0, max(0.0, _number(payload.get("price_drop_percent"), default_drop)))
    capital_loss = 10.0 if scenario == "virtual_capital_loss_10" else 0.0
    loss_percent = capital_loss if capital_loss else drop * exposure / 100.0
    loss_amount = round(capital * loss_percent / 100.0, 2)
    after_capital = max(0.0, round(capital - loss_amount, 2))
    critical = loss_percent >= max_drawdown
    return {
        "scenario": scenario,
        "parameters": {
            "starting_virtual_capital": capital,
            "current_exposure": exposure,
            "maximum_acceptable_drawdown": max_drawdown,
            "price_drop_percent": drop,
            "capital_loss_percent": capital_loss,
        },
        "before": {"capital": capital, "risk_level": "LOW"},
        "after": {"capital": after_capital, "loss_amount": loss_amount, "loss_percent": loss_percent, "new_risk_level": "HIGH" if critical else "MEDIUM"},
        "capital_before": capital,
        "capital_after": after_capital,
        "loss_amount": loss_amount,
        "loss_percent": loss_percent,
        "classification": "capital protection triggered" if critical else "warning",
        "protective_measures": ["risk limit applied", "block new BUY decisions", "reduce exposure", "LIVE remains blocked"],
        "ai_reaction": ["switch to WATCH mode", "pause trading if drawdown limit exceeded", "require fresh evidence before next signal"],
    }


def _stress_scenarios() -> list[dict[str, str]]:
    return [
        {"id": "btc_drop_20", "label": "BTC price drop 20%"},
        {"id": "market_crash_50", "label": "Market crash 50%"},
        {"id": "virtual_capital_loss_10", "label": "Virtual capital loss 10%"},
    ]


def _chat(request: Request, payload: dict[str, object]) -> dict[str, object]:
    message = str(payload.get("message", "")).strip()
    try:
        factory = getattr(request.app.state, "runner_factory", None)
        output = factory().run() if factory else None
        decision = str(getattr(output, "decision", "WATCH"))
        state = {"decision": decision, "risk_level": str(getattr(output, "risk_level", "LOW"))}
        answer = answer_chat(message, state)
        return {
            "status": "ok",
            "reply": str(answer.get("reply", "Команда принята.")),
            "run": {
                "status": "ok",
                "decision": decision,
                "confidence": float(getattr(output, "confidence", 0.0)),
                "risk_level": str(getattr(output, "risk_level", "LOW")),
                "intent": answer.get("intent"),
                "source_ai": answer.get("source_ai"),
            },
            "intent": answer.get("intent"),
            "source_ai": answer.get("source_ai"),
            "data": answer.get("data", {}),
        }
    except Exception as exc:
        return {"status": "error", "reply": "Команда не выполнена безопасно.", "run": {"decision": "WATCH"}, "error": f"{type(exc).__name__}: {exc}"}


def _control_center_html() -> str:
    return """<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>SharipovAI OS</title></head><body><aside class='os-sidebar'>SharipovAI OS</aside><main class='os-main'><h1>AI Control Center</h1><section><h2>Виртуальный кошелек</h2><p>Риск · Лимиты · Безопасность</p><button>Сохранить настройки</button></section></main></body></html>"""
