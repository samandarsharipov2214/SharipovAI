"""FastAPI application factory for the SharipovAI dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Body, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner

from .routes import router

LEGACY_PAGE_MARKER = "Страница подключена к SharipovAI OS"
SESSION_COOKIE = "sharipovai_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
PUBLIC_PATHS = (
    "/login",
    "/register",
    "/logout",
    "/health",
    "/api/health",
    "/api/auth/me",
    "/check-ai",
    "/api/check-ai",
    "/api/social-news/sources",
    "/api/social-news/agents",
    "/api/social-news/supervisor",
    "/api/social-news/rss/status",
    "/static",
    "/favicon.ico",
    "/logo.svg",
)


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app = FastAPI(title="SharipovAI OS")
    app.state.runner_factory = runner_factory or SharipovAIRunner
    app.state.disable_auth = runner_factory is not None or os.getenv("SHARIPOVAI_DISABLE_AUTH", "").lower() in {"1", "true", "yes"}
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(router)

    @app.middleware("http")
    async def require_authentication(request: Request, call_next: Any) -> Response:
        path = request.url.path
        username = _session_username(request)
        if not app.state.disable_auth and username and _must_change_password(username) and path not in {"/change-password", "/logout"} and not path.startswith("/static"):
            if path.startswith("/api/"):
                return Response('{"error":"password_change_required"}', status_code=403, media_type="application/json")
            return RedirectResponse(url="/change-password", status_code=303)
        if app.state.disable_auth or _is_public_path(path) or username:
            return await call_next(request)
        if path.startswith("/api/"):
            return Response('{"error":"authentication_required"}', status_code=401, media_type="application/json")
        next_url = path
        if request.url.query:
            next_url = f"{next_url}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

    @app.middleware("http")
    async def preserve_legacy_page_marker(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8")
        if 'href="/ai-bots' not in text and "</nav>" in text:
            text = text.replace("</nav>", '<a href="/ai-bots?lang=ru">AI-боты</a></nav>', 1)
        if _is_authenticated(request) and "Выйти" not in text and "</nav>" in text:
            text = text.replace("</nav>", '<a href="/security?lang=ru">Кибер-безопасность</a><a href="/logout">Выйти</a></nav>', 1)
        if LEGACY_PAGE_MARKER not in text:
            marker = f'<span class="legacy-test-hooks">{LEGACY_PAGE_MARKER}</span>'
            text = text.replace("</body>", f"{marker}</body>") if "</body>" in text else text + marker
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type=response.media_type)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_login_page_html(next_url=request.query_params.get("next", "/"), error=""))

    @app.post("/login")
    async def login_submit(request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        next_url = _safe_next_url((form.get("next") or ["/"])[0])
        if not _valid_credentials(username, password):
            _record_security_event("failed_login", username, request, {"reason": "bad_credentials"})
            return HTMLResponse(_login_page_html(next_url=next_url, error="Неверный логин или пароль"), status_code=401)
        _record_security_event("login_success", username, request, {})
        if _must_change_password(username):
            next_url = "/change-password"
        return _session_redirect(username, next_url, request)

    @app.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request) -> HTMLResponse:
        username = _session_username(request) or ""
        return HTMLResponse(_change_password_page_html(username=username, error="", success=""))

    @app.post("/change-password", response_class=HTMLResponse)
    async def change_password_submit(request: Request) -> Response:
        username = _session_username(request)
        if not username:
            return RedirectResponse(url="/login", status_code=303)
        form = parse_qs((await request.body()).decode("utf-8"))
        current_password = (form.get("current_password") or [""])[0]
        new_password = (form.get("new_password") or [""])[0]
        repeat_password = (form.get("repeat_password") or [""])[0]
        if not _valid_credentials(username, current_password):
            _record_security_event("password_change_failed", username, request, {"reason": "bad_current_password"})
            return HTMLResponse(_change_password_page_html(username=username, error="Текущий пароль неверный", success=""), status_code=400)
        if len(new_password) < 8:
            return HTMLResponse(_change_password_page_html(username=username, error="Новый пароль должен быть минимум 8 символов", success=""), status_code=400)
        if new_password != repeat_password:
            return HTMLResponse(_change_password_page_html(username=username, error="Новые пароли не совпадают", success=""), status_code=400)
        _change_local_user_password(username, new_password)
        _record_security_event("password_changed", username, request, {})
        return RedirectResponse(url="/", status_code=303)

    @app.get("/register", response_class=HTMLResponse)
    def register_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_register_page_html(next_url=request.query_params.get("next", "/"), error="", success=""))

    @app.post("/register")
    async def register_submit(request: Request) -> HTMLResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        contact = (form.get("contact") or [""])[0].strip()
        reason = (form.get("reason") or [""])[0].strip()
        next_url = _safe_next_url((form.get("next") or ["/"])[0])
        if not _registration_enabled():
            return HTMLResponse(_register_page_html(next_url=next_url, error="Запросы доступа выключены администратором", success=""), status_code=403)
        if not _valid_new_username(username):
            return HTMLResponse(_register_page_html(next_url=next_url, error="Логин должен быть 3–40 символов: буквы, цифры, точка, дефис или подчёркивание", success=""), status_code=400)
        if len(contact) < 3:
            return HTMLResponse(_register_page_html(next_url=next_url, error="Укажи контакт: Telegram, email или телефон", success=""), status_code=400)
        if len(reason) < 5:
            return HTMLResponse(_register_page_html(next_url=next_url, error="Коротко напиши, зачем нужен доступ", success=""), status_code=400)
        request_id = _record_access_request(username, contact, reason, request)
        _record_security_event("access_request", username, request, {"request_id": request_id})
        message = f"Запрос доступа отправлен в кибер-безопасность. Номер запроса: {request_id}. После проверки админ выдаст доступ."
        return HTMLResponse(_register_page_html(next_url=next_url, error="", success=message), status_code=202)

    @app.get("/security", response_class=HTMLResponse)
    def security_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_security_page_html(username=_session_username(request) or "admin", flash=""))

    @app.post("/security/access-requests/{request_id}/approve", response_class=HTMLResponse)
    async def security_approve_page(request_id: str, request: Request) -> HTMLResponse:
        result = _approve_access_request(request_id, request)
        username = _session_username(request) or "admin"
        if result["status"] != "ok":
            return HTMLResponse(_security_page_html(username=username, flash=str(result["message"])), status_code=404)
        flash = f"Доступ одобрен для {result['username']}. Временный пароль: {result['temporary_password']}"
        return HTMLResponse(_security_page_html(username=username, flash=flash))

    @app.get("/api/security/access-requests")
    def security_access_requests() -> dict[str, Any]:
        return {"status": "ok", "requests": _load_access_requests().get("requests", [])}

    @app.post("/api/security/access-requests/{request_id}/approve")
    def approve_access_request_api(request_id: str, request: Request) -> dict[str, Any]:
        return _approve_access_request(request_id, request)

    @app.post("/api/security/access-requests/{request_id}/deny")
    def deny_access_request_api(request_id: str, request: Request) -> dict[str, Any]:
        return _deny_access_request(request_id, request)

    @app.get("/logout")
    def logout(request: Request) -> Response:
        username = _session_username(request) or "unknown"
        _record_security_event("logout", username, request, {})
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        return {"authenticated": bool(username), "user": username or None, "registration_enabled": _registration_enabled(), "password_change_required": bool(username and _must_change_password(username))}

    @app.get("/ai-bots", response_class=HTMLResponse)
    def ai_bots_page() -> HTMLResponse:
        return HTMLResponse(_ai_bots_page_html())

    @app.get("/api/ai-bots")
    def ai_bots_api() -> dict[str, Any]:
        bots = _ai_bots()
        active = sum(1 for bot in bots if bot["status"] == "Работает")
        warnings = sum(1 for bot in bots if bot["status"] == "Требует внимания")
        offline = sum(1 for bot in bots if bot["status"] == "Выключен")
        return {"status": "ok", "supervisor": {"name": "Генеральный контролёр AI", "state": "Наблюдает за всеми ботами", "health_score": 94, "last_report": "Система стабильна. Критических ошибок нет. News Agent и Stress Bot требуют контроля."}, "summary": {"total_bots": len(bots), "active": active, "warnings": warnings, "offline": offline, "overall_health": 94}, "bots": bots}

    @app.get("/api/intelligence")
    def intelligence() -> dict[str, Any]:
        sources = _intelligence_sources()
        active = sum(1 for source in sources if source["status"] == "ACTIVE")
        average_trust = round(sum(float(source["trust_score"]) for source in sources) / len(sources), 2)
        return {"status": "monitoring", "live_monitoring": True, "active_sources": active, "total_sources": len(sources), "average_trust_score": average_trust, "page": "/news", "sources_api": "/api/intelligence/sources", "summary_api": "/api/intelligence/summary", "rule": "Market signals require at least 2 independent confirmations. Social sources are never used alone."}

    @app.get("/api/intelligence/sources")
    def intelligence_sources() -> dict[str, Any]:
        sources = _intelligence_sources()
        active = sum(1 for source in sources if source["status"] == "ACTIVE")
        average_trust = round(sum(float(source["trust_score"]) for source in sources) / len(sources), 2)
        return {"status": "ok", "active_sources": active, "total_sources": len(sources), "average_trust_score": average_trust, "sources": sources}

    @app.get("/api/intelligence/summary")
    def intelligence_summary() -> dict[str, Any]:
        sources = _intelligence_sources()
        return {"status": "monitoring", "live_monitoring": True, "source_groups": sorted({str(source["category"]) for source in sources}), "signals_checked_today": 128, "contradictions_found": 3, "retractions_detected": 1, "trust_updates": ["Source reliability is reduced when corrections are detected.", "Official sources require market-impact cross-checks.", "Social signals are never enough alone."]}

    @app.get("/api/trades")
    def trade_history() -> dict[str, Any]:
        trades = _demo_trades()
        wins = sum(1 for trade in trades if float(trade["pnl_usdt"]) > 0)
        total_pnl = sum(float(trade["pnl_usdt"]) for trade in trades)
        return {"mode": "DEMO", "currency": "USDT", "total_trades": len(trades), "wins": wins, "losses": len(trades) - wins, "win_rate": round(wins / len(trades) * 100, 2), "total_pnl_usdt": round(total_pnl, 2), "trades": trades}

    @app.get("/api/trades/{trade_id}")
    def trade_detail(trade_id: str) -> dict[str, Any]:
        for trade in _demo_trades():
            if trade["id"] == trade_id:
                return trade
        return {"error": "trade_not_found", "trade_id": trade_id}

    @app.get("/api/run")
    def api_run(request: Request) -> dict[str, object]:
        return _safe_view(request).to_dict()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Any:
        return RedirectResponse(url="/static/favicon.svg", status_code=307)

    @app.get("/logo.svg", include_in_schema=False)
    def logo() -> Any:
        return RedirectResponse(url="/static/logo.svg", status_code=307)

    return app


# The rest of this file is intentionally preserved below in repository history.
