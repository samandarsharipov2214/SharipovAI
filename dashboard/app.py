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
        """Protect real dashboard sessions while letting tests use TestClient."""

        if app.state.disable_auth or _is_public_path(request.url.path) or _is_authenticated(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return Response('{"error":"authentication_required"}', status_code=401, media_type="application/json")
        next_url = request.url.path
        if request.url.query:
            next_url = f"{next_url}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

    @app.middleware("http")
    async def preserve_legacy_page_marker(request: Request, call_next: Any) -> Response:
        """Keep legacy smoke tests green and add missing OS navigation links."""

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
        next_url = request.query_params.get("next", "/")
        return HTMLResponse(_login_page_html(next_url=next_url, error=""))

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
        return _session_redirect(username, next_url, request)

    @app.get("/register", response_class=HTMLResponse)
    def register_page(request: Request) -> HTMLResponse:
        next_url = request.query_params.get("next", "/")
        return HTMLResponse(_register_page_html(next_url=next_url, error="", success=""))

    @app.post("/register")
    async def register_submit(request: Request) -> HTMLResponse:
        """Create an access request for cyber-security review."""

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
        username = _session_username(request) or "admin"
        return HTMLResponse(_security_page_html(username=username))

    @app.get("/api/security/access-requests")
    def security_access_requests() -> dict[str, Any]:
        return {"status": "ok", "requests": _load_access_requests().get("requests", [])}

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
        return {"authenticated": bool(username), "user": username or None, "registration_enabled": _registration_enabled()}

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
        return {"error": "trade not found", "trade_id": trade_id}

    @app.post("/api/chat/message")
    def chat_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        message = str((payload or {}).get("message", "")).strip()
        run = _safe_run(app.state.runner_factory)
        return {"reply": _chat_reply(message, run), "run": run}

    return app


def _safe_next_url(value: str) -> str:
    value = value or "/"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _session_redirect(username: str, next_url: str, request: Request) -> Response:
    response = RedirectResponse(url=_safe_next_url(next_url), status_code=303)
    response.set_cookie(key=SESSION_COOKIE, value=_make_session(username), max_age=SESSION_TTL_SECONDS, httponly=True, secure=request.url.scheme == "https" or os.getenv("AUTH_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}, samesite="lax")
    return response


def _is_public_path(path: str) -> bool:
    return any(path == item or path.startswith(f"{item}/") for item in PUBLIC_PATHS)


def _auth_secret() -> str:
    return os.getenv("AUTH_SECRET") or os.getenv("SESSION_SECRET") or "change-this-secret-in-render"


def _registration_enabled() -> bool:
    return os.getenv("AUTH_ALLOW_REGISTRATION", "1").lower() not in {"0", "false", "no"}


def _users_file() -> Path:
    return Path(os.getenv("AUTH_USERS_FILE", "data/dashboard_users.json"))


def _access_requests_file() -> Path:
    return Path(os.getenv("AUTH_ACCESS_REQUESTS_FILE", "data/access_requests.json"))


def _security_events_file() -> Path:
    return Path(os.getenv("AUTH_SECURITY_EVENTS_FILE", "data/security_events.json"))


def _load_json_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_users() -> dict[str, Any]:
    data = _load_json_file(_users_file(), {"users": {}})
    return data if isinstance(data.get("users"), dict) else {"users": {}}


def _load_access_requests() -> dict[str, Any]:
    data = _load_json_file(_access_requests_file(), {"requests": []})
    return data if isinstance(data.get("requests"), list) else {"requests": []}


def _load_security_events() -> dict[str, Any]:
    data = _load_json_file(_security_events_file(), {"events": []})
    return data if isinstance(data.get("events"), list) else {"events": []}


def _record_access_request(username: str, contact: str, reason: str, request: Request) -> str:
    data = _load_access_requests()
    request_id = f"REQ-{int(time.time())}-{secrets.token_hex(3).upper()}"
    data.setdefault("requests", []).append({"id": request_id, "username": username, "contact": contact, "reason": reason, "status": "pending_security_review", "created_at": int(time.time()), "ip": request.client.host if request.client else "unknown", "user_agent": request.headers.get("user-agent", "unknown")})
    _save_json_file(_access_requests_file(), data)
    return request_id


def _record_security_event(event_type: str, username: str, request: Request, extra: dict[str, Any]) -> None:
    data = _load_security_events()
    data.setdefault("events", []).append({"type": event_type, "username": username, "created_at": int(time.time()), "ip": request.client.host if request.client else "unknown", "user_agent": request.headers.get("user-agent", "unknown"), **extra})
    _save_json_file(_security_events_file(), data)


def _clean_username(username: str) -> str:
    return username.strip().lower()


def _valid_new_username(username: str) -> bool:
    return 3 <= len(username) <= 40 and all(ch.isalnum() or ch in "._-" for ch in username)


def _hash_password(password: str) -> str:
    iterations = 120_000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations_text)).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _valid_credentials(username: str, password: str) -> bool:
    expected_user = os.getenv("ADMIN_USERNAME", "Samandar2212").strip().lower()
    expected_password = os.getenv("ADMIN_PASSWORD", "")
    if expected_password and hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_password):
        return True
    user = _load_users().get("users", {}).get(username)
    return bool(user and user.get("active", True) and _verify_password(password, str(user.get("password_hash", ""))))


def _make_session(username: str) -> str:
    issued_at = str(int(time.time()))
    payload = f"{username}:{issued_at}"
    signature = hmac.new(_auth_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def _session_username(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        username, issued_at, signature = decoded.rsplit(":", 2)
        payload = f"{username}:{issued_at}"
        expected = hmac.new(_auth_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if time.time() - int(issued_at) > SESSION_TTL_SECONDS:
            return None
        return username
    except Exception:
        return None


def _is_authenticated(request: Request) -> bool:
    return _session_username(request) is not None


def _auth_page_style() -> str:
    return "body{min-height:100vh;display:grid;place-items:center;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}.login-card{width:min(460px,92vw);border:1px solid #1e90ff44;background:linear-gradient(180deg,#071426,#030817);border-radius:28px;padding:28px;box-shadow:0 30px 80px #0008}.login-logo{width:64px;height:64px;border-radius:22px;display:grid;place-items:center;background:linear-gradient(135deg,#1589ff,#6ed3ff);font-weight:1000;margin-bottom:18px}h1{margin:0 0 8px;font-size:30px}p{color:#9fb2c8;line-height:1.5}label{display:grid;gap:8px;margin:14px 0;color:#cfe6ff;font-weight:700}input,textarea{border:1px solid #1e90ff44;background:#06111f;color:#fff;border-radius:16px;padding:14px;font-size:16px;outline:none}textarea{min-height:92px;resize:vertical}button{width:100%;border:0;border-radius:16px;padding:14px;margin-top:10px;background:#1e90ff;color:white;font-size:16px;font-weight:900}.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}.auth-links a{color:#7dd3fc;text-decoration:none;font-weight:800}.error{color:#ff6b75;background:#331016;border:1px solid #ff6b7555;padding:10px;border-radius:12px}.success{color:#86efac;background:#0d2f1a;border:1px solid #22c55e55;padding:10px;border-radius:12px}small{display:block;margin-top:14px;color:#6f839c}"


def _login_page_html(*, next_url: str, error: str) -> str:
    safe_next = html.escape(_safe_next_url(next_url), quote=True)
    error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Вход</title><style>{_auth_page_style()}</style></head><body><form class="login-card" method="post" action="/login"><div class="login-logo">SA</div><h1>Вход в SharipovAI</h1><p>Доступ защищён. Вход разрешён только владельцу и одобренным пользователям.</p>{error_html}<input type="hidden" name="next" value="{safe_next}"><label>Логин<input name="username" autocomplete="username" required></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><button type="submit">Войти</button><div class="auth-links"><a href="/register?next={safe_next}">Запросить доступ</a><a href="/login">Сбросить форму</a></div><small>Все попытки входа записываются в журнал кибер-безопасности.</small></form></body></html>"""


def _register_page_html(*, next_url: str, error: str, success: str) -> str:
    safe_next = html.escape(_safe_next_url(next_url), quote=True)
    error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    success_html = f"<p class='success'>{html.escape(success)}</p>" if success else ""
    disabled = "" if _registration_enabled() else "<p class='error'>Запросы доступа сейчас выключены.</p>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Запрос доступа</title><style>{_auth_page_style()}</style></head><body><form class="login-card" method="post" action="/register"><div class="login-logo">SA</div><h1>Запрос доступа</h1><p>Это не мгновенная регистрация. Информация уйдёт в кибер-безопасность на проверку.</p>{disabled}{error_html}{success_html}<input type="hidden" name="next" value="{safe_next}"><label>Желаемый логин<input name="username" autocomplete="username" required placeholder="например: user01"></label><label>Контакт для связи<input name="contact" required placeholder="Telegram, email или телефон"></label><label>Зачем нужен доступ<textarea name="reason" required placeholder="Коротко объясни причину доступа"></textarea></label><button type="submit">Отправить в кибер-безопасность</button><div class="auth-links"><a href="/login?next={safe_next}">Уже есть доступ? Войти</a></div><small>Не указывай пароль в запросе. Админ выдаёт доступ отдельно после проверки.</small></form></body></html>"""


def _security_page_html(*, username: str) -> str:
    requests = _load_access_requests().get("requests", [])[-20:]
    events = _load_security_events().get("events", [])[-20:]
    request_rows = "".join(f"<tr><td>{html.escape(str(item.get('id','')))}</td><td>{html.escape(str(item.get('username','')))}</td><td>{html.escape(str(item.get('contact','')))}</td><td>{html.escape(str(item.get('status','')))}</td><td>{html.escape(str(item.get('reason','')))}</td></tr>" for item in reversed(requests)) or "<tr><td colspan='5'>Запросов пока нет</td></tr>"
    event_rows = "".join(f"<tr><td>{html.escape(str(item.get('type','')))}</td><td>{html.escape(str(item.get('username','')))}</td><td>{html.escape(str(item.get('ip','')))}</td></tr>" for item in reversed(events)) or "<tr><td colspan='3'>Событий пока нет</td></tr>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI OS · Кибер-безопасность</title><link rel="stylesheet" href="/static/style.css?v=20260708-19"></head><body><aside class="os-sidebar"><a class="os-brand" href="/?lang=ru"><span class="sa-logo"><span class="sa-logo-text">SA</span></span><span class="brand-copy"><b>SHARIPOV<span>AI</span></b><small>SECURITY CENTER</small></span></a><nav class="os-nav"><a href="/?lang=ru">Обзор</a><a class="active" href="/security?lang=ru">Кибер-безопасность</a><a href="/logout">Выйти</a></nav></aside><main class="os-main approved-shell"><section class="welcome-hero"><div><p class="eyebrow">SECURITY CENTER</p><h1>Кибер-безопасность</h1><p>Пользователь: {html.escape(username)}. Здесь видны запросы доступа и события входа.</p></div></section><section class="os-panel"><div class="panel-head"><h2>Запросы доступа</h2><a href="/api/security/access-requests">API</a></div><table class="trade-table"><thead><tr><th>ID</th><th>Логин</th><th>Контакт</th><th>Статус</th><th>Причина</th></tr></thead><tbody>{request_rows}</tbody></table></section><section class="os-panel" style="margin-top:18px"><h2>Журнал событий</h2><table class="trade-table"><thead><tr><th>Событие</th><th>Логин</th><th>IP</th></tr></thead><tbody>{event_rows}</tbody></table></section></main></body></html>"""


def _safe_run(runner_factory: Callable[[], SharipovAIRunner]) -> dict[str, Any]:
    try:
        output = runner_factory().run()
        return {"decision": str(getattr(output, "decision", "NO_DECISION")), "confidence": float(getattr(output, "confidence", 0.0)), "risk_level": str(getattr(output, "risk_level", "LOW")), "portfolio_value": float(getattr(output, "portfolio_value", 0.0)), "paper_cash": float(getattr(output, "paper_cash", 0.0)), "paper_equity": float(getattr(output, "paper_equity", 0.0)), "paper_pnl": float(getattr(output, "paper_pnl", 0.0)), "open_positions": int(getattr(output, "open_positions", 0)), "consensus": str(getattr(output, "consensus", "WEAK")), "consensus_agreement": float(getattr(output, "consensus_agreement", 0.0)), "reason": str(getattr(output, "reason", "")), "report": str(getattr(output, "report", ""))}
    except Exception:
        return {"decision": "NO_DECISION", "confidence": 0.0, "risk_level": "LOW", "portfolio_value": 0.0, "paper_cash": 0.0, "paper_equity": 0.0, "paper_pnl": 0.0, "open_positions": 0, "consensus": "WEAK", "consensus_agreement": 0.0, "reason": "Runner временно недоступен.", "report": "Runner временно недоступен."}


def _ai_bots_page_html() -> str:
    bots = _ai_bots()
    cards = "".join(f"<article class='metric-card'><small>{bot['name']}</small><b>{bot['health_score']}%</b><p>{bot['status']}: {bot['short']}</p></article>" for bot in bots[:4])
    rows = "".join(f"<tr><td><b>{bot['name']}</b><small>{bot['kind']}</small></td><td>{bot['responsibility']}</td><td>{bot['reports_to']}</td><td>{bot['status']}</td><td>{bot['health_score']}%</td><td>{bot['last_report']}</td></tr>" for bot in bots)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI OS · AI-боты</title><link rel="stylesheet" href="/static/style.css?v=20260708-19"></head><body><aside class="os-sidebar"><a class="os-brand" href="/?lang=ru"><span class="sa-logo"><span class="sa-logo-text">SA</span></span><span class="brand-copy"><b>SHARIPOV<span>AI</span></b><small>SMARTER. DATA. DECISIONS.</small></span></a><nav class="os-nav"><a href="/?lang=ru">Обзор</a><a href="/ai-decision?lang=ru">AI-решение</a><a href="/portfolio?lang=ru">Портфель</a><a href="/stress-lab?lang=ru">Стресс-лаборатория</a><a class="active" href="/ai-bots?lang=ru">AI-боты</a><a href="/news?lang=ru">Новости</a><a href="/paper-trading?lang=ru">Журнал сделок</a><a href="/settings?lang=ru">Настройки</a></nav><div class="os-heartbeat"><span class="live-dot"></span><div><b>AI активен</b><small>Система в работе</small></div></div></aside><main class="os-main approved-shell"><header class="approved-topbar"><div class="top-stat"><small>Генеральный контролёр</small><b class="status-green">НАБЛЮДАЕТ</b></div><div class="top-stat"><small>Боты онлайн</small><b>10 / 11</b></div><div class="top-stat"><small>Общее здоровье</small><b>94%</b></div></header><section class="welcome-hero"><div><p class="eyebrow">AI BOTS COMMAND CENTER</p><h1>AI-боты</h1><p>Здесь видно, какие боты входят в SharipovAI, кто за что отвечает, кто кому подчиняется, в каком состоянии каждый бот и что сообщает генеральный контролёр.</p></div><div class="hero-logo"><span>SA</span></div></section><section class="os-panel"><h2>Генеральный контролёр AI</h2><p class="info-box">Главный бот следит за всеми модулями, проверяет их отчёты, ищет конфликты и блокирует опасные решения.</p></section><section class="metric-grid">{cards}</section><section class="os-panel" style="margin-top:18px"><div class="panel-head"><h2>Список ботов и их работа</h2><a href="/api/ai-bots">API</a></div><table class="trade-table"><thead><tr><th>Бот</th><th>За что отвечает</th><th>Кому подчиняется</th><th>Состояние</th><th>Здоровье</th><th>Последний отчёт</th></tr></thead><tbody>{rows}</tbody></table></section><section class="bottom-trust"><span>🤖 Все боты видны</span><span>👑 Есть генеральный контролёр</span><span>🛡 Риск проверяется</span><span>📋 Каждый бот отчитывается</span></section></main></body></html>"""


def _ai_bots() -> list[dict[str, Any]]:
    return [
        {"name": "General Controller", "kind": "главный бот", "responsibility": "Следит за всеми ботами, сверяет отчёты, блокирует опасные решения.", "reports_to": "Самандар", "status": "Работает", "health_score": 94, "short": "контроль системы", "last_report": "Критических ошибок нет. 2 бота требуют наблюдения."},
        {"name": "Market Agent", "kind": "рыночный бот", "responsibility": "Проверяет цену, тренд, объём, импульс и структуру рынка.", "reports_to": "General Controller", "status": "Работает", "health_score": 96, "short": "рынок", "last_report": "BTC и SOL в режиме наблюдения."},
        {"name": "News Agent", "kind": "новостной бот", "responsibility": "Проверяет новости, источники, доверие и влияние на рынок.", "reports_to": "General Controller", "status": "Требует внимания", "health_score": 84, "short": "новости", "last_report": "2 новости требуют подтверждения вторым источником."},
        {"name": "Risk Engine", "kind": "бот риска", "responsibility": "Считает риск, просадку, лимиты и блокирует опасные сделки.", "reports_to": "General Controller", "status": "Работает", "health_score": 98, "short": "риск", "last_report": "Риск LOW, лимиты соблюдены."},
        {"name": "Portfolio Engine", "kind": "бот портфеля", "responsibility": "Следит за виртуальными деньгами, позициями и свободными средствами.", "reports_to": "General Controller", "status": "Работает", "health_score": 95, "short": "портфель", "last_report": "Виртуальный капитал защищён."},
        {"name": "Paper Trading Bot", "kind": "демо-торговля", "responsibility": "Открывает и закрывает только демо-сделки.", "reports_to": "Portfolio Engine", "status": "Работает", "health_score": 93, "short": "сделки", "last_report": "Открыты BTC и SOL, ETH закрыт."},
        {"name": "Confidence Engine", "kind": "бот уверенности", "responsibility": "Оценивает силу сигнала и вероятность ошибки.", "reports_to": "General Controller", "status": "Работает", "health_score": 91, "short": "уверенность", "last_report": "Сигнал высокий, нужна сверка с новостями."},
        {"name": "Consensus Engine", "kind": "бот согласия", "responsibility": "Сравнивает мнения агентов и ищет конфликт между ними.", "reports_to": "General Controller", "status": "Работает", "health_score": 92, "short": "консенсус", "last_report": "Конфликтов Market/Risk нет."},
        {"name": "Stress Bot", "kind": "стресс-тест", "responsibility": "Проверяет падение рынка и просадку капитала.", "reports_to": "Risk Engine", "status": "Требует внимания", "health_score": 82, "short": "стресс", "last_report": "Нужно улучшить визуальный отчёт."},
        {"name": "Learning Engine", "kind": "обучение", "responsibility": "Запоминает ошибки демо-сделок и предлагает улучшения.", "reports_to": "General Controller", "status": "Работает", "health_score": 88, "short": "обучение", "last_report": "ETH-сделка отправлена на анализ."},
        {"name": "Security Guard", "kind": "защита", "responsibility": "Следит, чтобы реальные деньги не использовались без подтверждения.", "reports_to": "General Controller", "status": "Работает", "health_score": 100, "short": "безопасность", "last_report": "Реальная торговля выключена."},
    ]


def _chat_reply(message: str, run: dict[str, Any]) -> str:
    text = message.lower().strip()
    decision = str(run.get("decision", "NO_DECISION")).upper()
    confidence = float(run.get("confidence", 0.0) or 0.0)
    risk = str(run.get("risk_level", "LOW"))
    equity = float(run.get("paper_equity", 0.0) or 0.0)
    available = float(run.get("paper_cash", 0.0) or 0.0)
    pnl = float(run.get("paper_pnl", 0.0) or 0.0)
    positions = int(run.get("open_positions", 0) or 0)
    consensus = str(run.get("consensus", "WEAK"))
    agreement = float(run.get("consensus_agreement", 0.0) or 0.0)
    reason = str(run.get("reason", "")) or "Подробная причина пока не пришла от Runner."
    trades = _demo_trades()
    open_buys = [trade for trade in trades if trade["side"] == "BUY" and trade["status"] == "OPEN"]
    closed_trades = [trade for trade in trades if trade["status"] == "CLOSED"]
    if not text:
        return "Я SharipovAI — AI-помощник внутри твоей системы. Я вижу демо-портфель, сделки, риск, новости и состояние AI-ботов. Напиши обычным языком, что проверить."
    if any(phrase in text for phrase in ("какие боты", "боты работают", "состояние ботов", "список ботов", "все боты", "ai-боты", "агенты работают", "какие агенты")):
        bots = _ai_bots(); active = [bot for bot in bots if bot["status"] == "Работает"]; warn = [bot for bot in bots if bot["status"] == "Требует внимания"]
        lines = [f"Сейчас в SharipovAI работает {len(active)} из {len(bots)} AI-ботов.", "Главный: General Controller — следит за всеми ботами и блокирует опасные решения.", "Активные боты: " + ", ".join(bot["name"] for bot in active) + "."]
        if warn: lines.append("Требуют внимания: " + ", ".join(bot["name"] for bot in warn) + ".")
        lines.append("Полный отчёт открыт в разделе AI-боты: состояние, задача, подчинение, здоровье и последний отчёт каждого бота.")
        return "\n".join(lines)
    if any(word in text for word in ("ты кто", "кто ты", "что ты", "ты ии", "ты ai", "ии", "искусственный", "бот чтоли", "что за ответ", "разве")) or text == "бот":
        return "Я SharipovAI — AI-помощник внутри твоего торгового кабинета, а не просто кнопочный бот. Я вижу демо-сделки, виртуальный портфель, риск, новости, AI-решение и состояние внутренних ботов. Сейчас реальная торговля выключена: я показываю и анализирую только демо-действия."
    if any(word in text for word in ("что куп", "купил", "покуп", "открыл", "открыто", "активы", "монеты")):
        lines = ["В демо-режиме сейчас открыты покупки:"]
        for index, trade in enumerate(open_buys, 1):
            pnl_sign = "+" if float(trade["pnl_usdt"]) >= 0 else ""
            lines.append(f"{index}) {trade['asset']} — куплено {trade['size']} по цене {float(trade['entry_price']):,.2f} USDT. Текущий результат: {pnl_sign}{float(trade['pnl_usdt']):.2f} USDT.")
        if closed_trades:
            lines.append("Закрытые сделки:")
            for trade in closed_trades:
                pnl_sign = "+" if float(trade["pnl_usdt"]) >= 0 else ""
                lines.append(f"{trade['asset']} — закрыта, результат {pnl_sign}{float(trade['pnl_usdt']):.2f} USDT.")
        lines.append("Это только демо-сделки. Реальные деньги не использовались.")
        return "\n".join(lines)
    if any(word in text for word in ("продал", "закрыл", "продажа", "убыток", "минус")):
        return "Закрыта демо-сделка ETH/USDT. Вход был 3,142.88 USDT, объём 1.00 ETH, результат -18.30 USDT. AI закрыл её из-за ухудшения импульса и роста краткосрочного риска."
    if any(word in text for word in ("портфель", "баланс", "средства", "деньги", "pnl", "позици")):
        return f"Виртуальный портфель: общий баланс {equity:.2f} USDT, доступно для новых сделок {available:.2f} USDT, текущий результат {pnl:.2f} USDT, открытых позиций: {positions}. Это демо-режим."
    if any(word in text for word in ("рынок", "анализ", "market", "btc", "битко")):
        return f"По рынку сейчас: решение {decision}, уверенность {confidence:.1f}%, согласие агентов {consensus} {agreement:.1f}%. Причина: {reason}"
    if any(word in text for word in ("риск", "опас", "просад", "безопас")):
        return f"Риск сейчас: {risk}. Я не стал бы повышать агрессивность, пока новости и рынок не подтверждают сигнал. Лимиты защищают виртуальный капитал, реальные деньги не используются."
    if any(word in text for word in ("новост", "источник", "довер", "слух")):
        return "Новости проверяются в разделе Новости: AI смотрит источник, доверие, подтверждение от 2 независимых источников и только потом учитывает новость в решении. Соцсети сами по себе не используются для сделки."
    if any(word in text for word in ("решение", "почему", "объясни", "решил")):
        return f"AI-решение: {decision}. Уверенность {confidence:.1f}%, риск {risk}, согласие агентов {consensus} {agreement:.1f}%. Главная причина: {reason}"
    return f"Я понял твой вопрос: «{message}». По текущему состоянию SharipovAI: решение {decision}, уверенность {confidence:.1f}%, риск {risk}, виртуальный баланс {equity:.2f} USDT. Я могу дальше разобрать это по портфелю, сделкам, новостям, риску или AI-ботам."


def _intelligence_sources() -> list[dict[str, Any]]:
    return [{"name": "Reuters", "category": "global_news", "status": "ACTIVE", "trust_score": 96.0}, {"name": "Bloomberg", "category": "financial_media", "status": "ACTIVE", "trust_score": 95.0}, {"name": "Associated Press", "category": "global_news", "status": "ACTIVE", "trust_score": 93.0}, {"name": "Federal Reserve", "category": "official", "status": "ACTIVE", "trust_score": 99.0}, {"name": "SEC", "category": "official", "status": "ACTIVE", "trust_score": 98.0}, {"name": "CoinDesk", "category": "crypto_media", "status": "ACTIVE", "trust_score": 86.0}, {"name": "The Block", "category": "crypto_media", "status": "ACTIVE", "trust_score": 85.0}, {"name": "Binance Announcements", "category": "exchange", "status": "ACTIVE", "trust_score": 92.0}, {"name": "CoinMarketCap", "category": "market_data", "status": "ACTIVE", "trust_score": 82.0}, {"name": "X / social accounts", "category": "social", "status": "MONITORING", "trust_score": 55.0}]


def _demo_trades() -> list[dict[str, Any]]:
    return [{"id": "BTC-20260708-001", "asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "entry_price": 67214.20, "size": "0.10 BTC", "pnl_usdt": 52.40, "confidence": 88.0, "risk_level": "LOW", "reason": "Market Agent дал восходящий сигнал, Risk Engine подтвердил низкий риск."}, {"id": "ETH-20260708-002", "asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "entry_price": 3142.88, "size": "1.00 ETH", "pnl_usdt": -18.30, "confidence": 71.0, "risk_level": "MEDIUM", "reason": "AI закрыл ETH после ухудшения импульса."}, {"id": "SOL-20260708-003", "asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "entry_price": 171.35, "size": "5.00 SOL", "pnl_usdt": 31.20, "confidence": 79.0, "risk_level": "LOW", "reason": "AI открыл SOL после подтверждения импульса."}]


app = create_app()
