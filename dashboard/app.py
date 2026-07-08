"""FastAPI application factory for the SharipovAI dashboard.

Render currently starts the service with:

    uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT

So this module must expose a module-level `app` object. Keep this file small and
stable; feature APIs are installed by their own modules.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner

from .evidence_recorder_middleware import install_evidence_recorder_middleware
from .policy_guard_middleware import install_policy_guard_middleware
from .routes import router
from .user_admin import create_user, hash_password, verify_password

SESSION_COOKIE = "sharipovai_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    """Create the FastAPI dashboard application."""

    app_instance = FastAPI(title="SharipovAI OS")
    app_instance.state.runner_factory = runner_factory or SharipovAIRunner
    app_instance.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app_instance.include_router(router)
    _install_feature_apis(app_instance)
    _install_auth_entrypoints(app_instance)
    install_evidence_recorder_middleware(app_instance)
    install_policy_guard_middleware(app_instance)
    _install_public_entrypoints(app_instance)
    return app_instance


def _install_feature_apis(app_instance: FastAPI) -> None:
    """Install optional feature APIs without breaking startup if one module fails."""

    installers: list[tuple[str, str]] = [
        ("dashboard.exchange_api", "install_exchange_api"),
        ("dashboard.demo_api", "install_demo_api"),
        ("dashboard.social_news_api", "install_social_news_api"),
        ("dashboard.public_check_api", "install_public_check_api"),
        ("dashboard.trading_intelligence_api", "install_trading_intelligence_api"),
        ("dashboard.telegram_webhook_api", "install_telegram_webhook_api"),
        ("dashboard.learning_os_api", "install_learning_os_api"),
        ("dashboard.evidence_vault_api", "install_evidence_vault_api"),
        ("dashboard.launch_check_api", "install_launch_check_api"),
    ]
    for module_name, function_name in installers:
        try:
            module = __import__(module_name, fromlist=[function_name])
            installer = getattr(module, function_name)
            installer(app_instance)
        except Exception as exc:  # pragma: no cover - startup safety fallback
            _install_feature_error_endpoint(app_instance, module_name, exc)


def _install_feature_error_endpoint(app_instance: FastAPI, module_name: str, exc: Exception) -> None:
    """Expose a compact startup warning without failing the whole backend."""

    error_key = module_name.replace(".", "_").replace("-", "_")

    @app_instance.get(f"/api/startup-warning/{error_key}")
    def startup_warning() -> dict[str, Any]:
        return {"status": "warning", "module": module_name, "error": f"{type(exc).__name__}: {exc}"}


def _install_auth_entrypoints(app_instance: FastAPI) -> None:
    """Install login, access-request, and password-change routes used by tests and secure apps."""

    if getattr(app_instance.state, "auth_entrypoints_installed", False):
        return
    app_instance.state.auth_entrypoints_installed = True

    @app_instance.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_login_page_html(next_url=_safe_next_url(request.query_params.get("next", "/")), error=""))

    @app_instance.post("/login")
    async def login_submit(request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        next_url = _safe_next_url((form.get("next") or ["/"])[0])
        if not _valid_credentials(username, password):
            _record_security_event("failed_login", username or "anonymous", request, {"reason": "bad_credentials"})
            return HTMLResponse(_login_page_html(next_url=next_url, error="Неверный логин или пароль"), status_code=401)
        users = _load_users()
        user = _user_record(users, username)
        target = "/change-password" if user and user.get("must_change_password") else next_url
        response = RedirectResponse(url=target, status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=_make_session(username),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
        )
        _record_security_event("login_success", username, request, {"target": target})
        return response

    @app_instance.get("/logout")
    def logout() -> Response:
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app_instance.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request) -> HTMLResponse:
        if not _session_username(request):
            return HTMLResponse(_login_page_html(next_url="/change-password", error="Сначала войдите"), status_code=401)
        return HTMLResponse(_change_password_html(error=""))

    @app_instance.post("/change-password")
    async def change_password_submit(request: Request) -> Response:
        username = _session_username(request)
        if not username:
            return HTMLResponse(_login_page_html(next_url="/change-password", error="Сначала войдите"), status_code=401)
        form = parse_qs((await request.body()).decode("utf-8"))
        current_password = (form.get("current_password") or [""])[0]
        new_password = (form.get("new_password") or [""])[0]
        repeat_password = (form.get("repeat_password") or [""])[0]
        users = _load_users()
        user = _user_record(users, username)
        if not user or not verify_password(current_password, str(user.get("password_hash", ""))):
            return HTMLResponse(_change_password_html(error="Текущий пароль неверный"), status_code=401)
        if len(new_password) < 8 or new_password != repeat_password:
            return HTMLResponse(_change_password_html(error="Новый пароль слишком короткий или не совпадает"), status_code=400)
        user["password_hash"] = hash_password(new_password)
        user["must_change_password"] = False
        user["password_changed_at"] = int(time.time())
        _save_users(users)
        _record_security_event("password_changed", username, request, {})
        return RedirectResponse(url="/", status_code=303)

    @app_instance.post("/register", response_class=HTMLResponse)
    async def register(request: Request) -> HTMLResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        contact = ((form.get("contact") or [""])[0]).strip()
        reason = ((form.get("reason") or [""])[0]).strip()
        if not username:
            return HTMLResponse(_register_result_html("Некорректный логин"), status_code=400)
        requests_data = _load_access_requests()
        items = requests_data.setdefault("requests", [])
        request_id = f"REQ-{secrets.token_hex(6).upper()}"
        items.append(
            {
                "id": request_id,
                "username": username,
                "contact": contact,
                "reason": reason,
                "status": "pending_security_review",
                "created_at": int(time.time()),
            }
        )
        _save_access_requests(requests_data)
        _record_security_event("access_requested", username, request, {"request_id": request_id})
        return HTMLResponse(_register_result_html("Запрос доступа отправлен"), status_code=202)

    @app_instance.get("/api/security/access-requests")
    def access_requests() -> dict[str, Any]:
        requests_data = _load_access_requests()
        return {"status": "ok", "requests": list(requests_data.get("requests", []))}

    @app_instance.post("/api/security/access-requests/{request_id}/approve")
    def approve_access_request(request_id: str, request: Request) -> dict[str, Any]:
        requests_data = _load_access_requests()
        items = requests_data.setdefault("requests", [])
        target = next((item for item in items if str(item.get("id")) == request_id), None)
        if not isinstance(target, dict):
            return {"status": "not_found", "request_id": request_id}
        username = _clean_username(str(target.get("username", "")))
        temporary_password = f"SA-{secrets.token_hex(6)}"
        users = _load_users()
        result = create_user(users, username, temporary_password, role="user", must_change_password=True)
        if result.get("status") == "already_exists":
            user = _user_record(users, username)
            if user is not None:
                user["password_hash"] = hash_password(temporary_password)
                user["must_change_password"] = True
                user["active"] = True
                result = {"status": "ok", "username": username, "role": user.get("role", "user")}
        _save_users(users)
        target["status"] = "approved"
        target["approved_at"] = int(time.time())
        _save_access_requests(requests_data)
        _record_security_event("access_approved", username, request, {"request_id": request_id})
        return {"status": "ok", "username": username, "temporary_password": temporary_password, "user_status": result.get("status", "ok")}

    @app_instance.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        return {"authenticated": bool(username), "user": username or None}


def _install_public_entrypoints(app_instance: FastAPI) -> None:
    """Install simple public pages for mobile checks."""

    @app_instance.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app_instance.get("/api/health")
    def api_health() -> dict[str, str]:
        return {"status": "ok"}

    @app_instance.get("/", response_class=HTMLResponse)
    def root_page() -> HTMLResponse:
        headlines = _home_headlines()
        return HTMLResponse(
            f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI</title><style>body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{padding:18px;max-width:980px;margin:auto}}.card{{background:#111827;border:1px solid #253047;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}}.news{{background:#0b1220;border:1px solid #1f2a3d;border-radius:16px;padding:13px}}.news b{{display:block;margin-bottom:7px}}small{{color:#8ea2c4;display:block;line-height:1.4}}a{{color:#60a5fa;font-weight:800}}.ok{{display:inline-block;background:#10b981;color:#04140d;border-radius:999px;padding:7px 12px;font-weight:900}}.nav{{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}}</style></head><body><main><section class="card"><span class="ok">LIVE</span><h1>SharipovAI живой</h1><p>Система показывает новости, AI Scoreboard, Trade Gate, Learning OS, Evidence Vault, Telegram webhook и финальный Launch Check.</p><div class="nav"><a href="/launch-check">Launch Check</a><a href="/evidence-vault">Evidence Vault</a><a href="/news-live">Новости</a><a href="/ai-scoreboard">AI Scoreboard</a><a href="/trade-gate">Можно ли торговать?</a><a href="/learning-os">Learning OS</a><a href="/learning-v2">Learning V2</a><a href="/system-ai-audit">Все ИИ</a><a href="/telegram-check">Telegram Check</a></div></section><section class="card"><h2>Самые обсуждаемые новости</h2><div class="grid">{headlines}</div></section><section class="card"><h2>Быстрая проверка</h2><p><a href="/api/launch-check">JSON Launch Check</a></p><p><a href="/api/evidence-vault/snapshot">JSON Evidence Vault</a></p><p><a href="/api/ai-scoreboard">JSON AI Scoreboard</a></p><p><a href="/api/trade-gate">JSON Trade Gate</a></p><p><a href="/api/learning-os/snapshot">JSON Learning OS</a></p><p><a href="/api/telegram/status">JSON Telegram Bot</a></p></section></main></body></html>"""
        )


def _home_headlines() -> str:
    """Return compact news cards for the home page."""

    try:
        from news_monitor.analyzer import analyzed_news_payload

        news = analyzed_news_payload()
        items = list(news.get("items", []))[:6]
    except Exception as exc:  # pragma: no cover - safe public fallback
        return f"<article class='news'><b>Новости временно недоступны</b><small>{escape(type(exc).__name__)}</small></article>"
    if not items:
        return "<article class='news'><b>Новостей пока нет</b><small>Жду обновления источников</small></article>"
    cards = []
    for item in items:
        title = escape(str(item.get("title", "Новость")))
        source = escape(str(item.get("source_name", "Источник")))
        credibility = escape(str(item.get("credibility_percent", item.get("trust_score", 0))))
        action = escape(str(item.get("ai_action", "WATCH")))
        cards.append(f"<article class='news'><b>{title}</b><small>{source}</small><small>Достоверность: {credibility}% · AI: {action}</small></article>")
    return "".join(cards)


def _clean_username(username: str) -> str:
    return username.strip().lower()


def _users_file() -> Path:
    return Path(os.getenv("AUTH_USERS_FILE", "data/dashboard_users.json"))


def _access_requests_file() -> Path:
    return Path(os.getenv("AUTH_ACCESS_REQUESTS_FILE", "data/access_requests.json"))


def _security_events_file() -> Path:
    return Path(os.getenv("AUTH_SECURITY_EVENTS_FILE", "data/security_events.json"))


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_users() -> dict[str, Any]:
    return _load_json(_users_file(), {"users": {}})


def _save_users(data: dict[str, Any]) -> None:
    _write_json(_users_file(), data)


def _load_access_requests() -> dict[str, Any]:
    return _load_json(_access_requests_file(), {"requests": []})


def _save_access_requests(data: dict[str, Any]) -> None:
    _write_json(_access_requests_file(), data)


def _user_record(users_data: dict[str, Any], username: str) -> dict[str, Any] | None:
    users = users_data.setdefault("users", {})
    user = users.get(_clean_username(username)) if isinstance(users, dict) else None
    return user if isinstance(user, dict) else None


def _auth_secret() -> str:
    return os.getenv("AUTH_SECRET") or os.getenv("SESSION_SECRET") or "change-this-secret-in-render"


def _valid_credentials(username: str, password: str) -> bool:
    clean = _clean_username(username)
    expected_user = _clean_username(os.getenv("ADMIN_USERNAME", ""))
    expected_password = os.getenv("ADMIN_PASSWORD", "")
    if expected_user and expected_password and hmac.compare_digest(clean, expected_user) and hmac.compare_digest(password, expected_password):
        return True
    user = _user_record(_load_users(), clean)
    if not user or not bool(user.get("active", True)):
        return False
    return verify_password(password, str(user.get("password_hash", "")))


def _make_session(username: str) -> str:
    issued_at = str(int(time.time()))
    payload = f"{_clean_username(username)}:{issued_at}"
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
        return _clean_username(username)
    except Exception:
        return None


def _safe_next_url(value: str | None) -> str:
    next_url = (value or "/").strip() or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def _record_security_event(event_type: str, username: str, request: Request | None, metadata: dict[str, Any] | None = None) -> None:
    path = _security_events_file()
    data = _load_json(path, {"events": []})
    events = data.setdefault("events", [])
    client_host = ""
    if request is not None and request.client is not None:
        client_host = request.client.host
    events.append(
        {
            "type": event_type,
            "username": _clean_username(username),
            "path": str(request.url.path) if request is not None else "",
            "client": client_host,
            "metadata": metadata or {},
            "created_at": int(time.time()),
        }
    )
    _write_json(path, data)


def _login_page_html(*, next_url: str, error: str) -> str:
    safe_next = escape(_safe_next_url(next_url), quote=True)
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Вход</title><style>body{{min-height:100vh;display:grid;place-items:center;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}}.login-card{{width:min(430px,92vw);border:1px solid #1e90ff44;background:linear-gradient(180deg,#071426,#030817);border-radius:28px;padding:28px;box-shadow:0 30px 80px #0008}}.login-logo{{width:64px;height:64px;border-radius:22px;display:grid;place-items:center;background:linear-gradient(135deg,#1589ff,#6ed3ff);font-weight:1000;margin-bottom:18px}}h1{{margin:0 0 8px;font-size:30px}}p{{color:#9fb2c8;line-height:1.5}}label{{display:grid;gap:8px;margin:14px 0;color:#cfe6ff;font-weight:700}}input,textarea{{border:1px solid #1e90ff44;background:#06111f;color:#fff;border-radius:16px;padding:14px;font-size:16px;outline:none}}button{{width:100%;border:0;border-radius:16px;padding:14px;margin-top:10px;background:#1e90ff;color:white;font-size:16px;font-weight:900}}.error{{color:#ff6b75;background:#331016;border:1px solid #ff6b7555;padding:10px;border-radius:12px}}a{{color:#7dd3fc;font-weight:800}}small{{display:block;margin-top:14px;color:#6f839c}}</style></head><body><form class="login-card" method="post" action="/login"><div class="login-logo">SA</div><h1>Вход в SharipovAI</h1><p>Панель, Telegram Mini App и будущий iOS-клиент работают через один защищённый backend.</p>{error_html}<input type="hidden" name="next" value="{safe_next}"><label>Логин<input name="username" autocomplete="username" required></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><button type="submit">Войти</button><small><a href="/register-page">Запросить доступ</a></small></form></body></html>"""


def _change_password_html(error: str) -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Смена пароля</title><style>body{{min-height:100vh;display:grid;place-items:center;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}}form{{width:min(430px,92vw);border:1px solid #1e90ff44;background:#071426;border-radius:28px;padding:28px}}label{{display:grid;gap:8px;margin:14px 0}}input{{border:1px solid #1e90ff44;background:#06111f;color:#fff;border-radius:16px;padding:14px}}button{{width:100%;border:0;border-radius:16px;padding:14px;background:#1e90ff;color:#fff;font-weight:900}}.error{{color:#ff6b75}}</style></head><body><form method="post" action="/change-password"><h1>Сменить временный пароль</h1>{error_html}<label>Текущий пароль<input name="current_password" type="password" required></label><label>Новый пароль<input name="new_password" type="password" required></label><label>Повторить пароль<input name="repeat_password" type="password" required></label><button type="submit">Сохранить</button></form></body></html>"""


def _register_result_html(message: str) -> str:
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>SharipovAI · Доступ</title></head><body><main><h1>{escape(message)}</h1><p><a href='/login'>Вернуться ко входу</a></p></main></body></html>"


# Required for Render start command: uvicorn dashboard.app:app
app = create_app()


__all__ = (
    "SESSION_COOKIE",
    "app",
    "create_app",
    "_clean_username",
    "_load_users",
    "_login_page_html",
    "_record_security_event",
    "_safe_next_url",
    "_session_username",
    "_valid_credentials",
)
