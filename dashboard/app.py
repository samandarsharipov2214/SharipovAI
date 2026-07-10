"""FastAPI application factory for the SharipovAI dashboard."""
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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from runner import SharipovAIRunner
from .routes import router
from .user_admin import hash_password, verify_password

SESSION_COOKIE = "sharipovai_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 14)))
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "12"))


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    app = FastAPI(title="SharipovAI OS", docs_url=None if _is_production() else "/docs", redoc_url=None)
    app.state.runner_factory = runner_factory or SharipovAIRunner
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(router)
    _install_feature_apis(app)
    _install_auth(app)
    _install_auth_guard(app)
    return app


def _install_feature_apis(app: FastAPI) -> None:
    installers = [
        ("dashboard.exchange_api", "install_exchange_api"),
        ("dashboard.demo_api", "install_demo_api"),
        ("dashboard.social_news_api", "install_social_news_api"),
        ("dashboard.public_check_api", "install_public_check_api"),
        ("dashboard.trading_intelligence_api", "install_trading_intelligence_api"),
        ("dashboard.telegram_webhook_api", "install_telegram_webhook_api"),
        ("dashboard.learning_os_api", "install_learning_os_api"),
        ("dashboard.evidence_vault_api", "install_evidence_vault_api"),
        ("dashboard.bot_communication_api", "install_bot_communication_api"),
        ("dashboard.paper_activity_api", "install_paper_activity_api"),
        ("dashboard.autonomous_learning_api", "install_autonomous_learning_api"),
        ("dashboard.realtime_status_api", "install_realtime_status_api"),
        ("dashboard.launch_check_api", "install_launch_check_api"),
    ]
    for module_name, function_name in installers:
        try:
            module = __import__(module_name, fromlist=[function_name])
            getattr(module, function_name)(app)
        except Exception as exc:
            key = module_name.replace(".", "_")

            @app.get(f"/api/startup-warning/{key}")
            def warning(module_name: str = module_name, exc: Exception = exc) -> dict[str, Any]:
                return {"status": "warning", "module": module_name, "error": f"{type(exc).__name__}: {exc}"}


def _install_auth_guard(app: FastAPI) -> None:
    public_api = (
        "/api/health", "/api/security", "/api/telegram", "/api/public", "/api/social-news",
        "/api/demo", "/api/stress-lab", "/api/crash-test", "/api/translations", "/api/ai-bots",
        "/api/chat/message", "/api/ai-improvement", "/api/startup-warning",
    )

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        disabled = os.getenv("SHARIPOVAI_DISABLE_AUTH", "0").lower() in {"1", "true", "yes"}
        path = request.url.path
        if not disabled and path.startswith("/api/") and not path.startswith(public_api):
            if not _session_username(request):
                return JSONResponse({"status": "unauthorized"}, status_code=401)
        return await call_next(request)


def _install_auth(app: FastAPI) -> None:
    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        next_url = _safe_next(request.query_params.get("next", "/"))
        return HTMLResponse(_login_html(next_url, ""))

    @app.post("/login")
    async def login_submit(request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        next_url = _safe_next((form.get("next") or ["/"])[0])
        if not _valid_credentials(username, password):
            return HTMLResponse(_login_html(next_url, "Неверный логин, пароль или доступ ещё не одобрен"), status_code=401)
        user = _load_users().get(username, {})
        target = "/change-password" if user.get("must_change_password") else next_url
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(SESSION_COOKIE, _make_session(username), max_age=SESSION_TTL_SECONDS, httponly=True, secure=_is_production(), samesite="lax", path="/")
        return response

    @app.get("/logout")
    def logout() -> Response:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.post("/register")
    async def register(request: Request) -> HTMLResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean((form.get("username") or [""])[0])
        contact = (form.get("contact") or [""])[0].strip()
        reason = (form.get("reason") or [""])[0].strip()
        password = (form.get("password") or [""])[0]
        if not username:
            return HTMLResponse(_result_html("Нужен логин."), status_code=400)
        requests = _load_requests()
        if any(str(v.get("username")) == username and str(v.get("status", "")).startswith("pending") for v in requests.values()):
            return HTMLResponse(_result_html("Заявка уже существует."), status_code=409)
        request_id = f"REQ-{int(time.time())}-{secrets.token_hex(3)}"
        requests[request_id] = {"username": username, "contact": contact, "reason": reason, "status": "pending_security_review", "created_at": int(time.time())}
        _save_requests(requests)
        if password and len(password) >= MIN_PASSWORD_LENGTH:
            users = _load_users()
            users[username] = {"password_hash": hash_password(password), "active": False, "role": "pending", "must_change_password": False}
            _save_users(users)
        return HTMLResponse(_result_html("Запрос доступа отправлен. Ожидайте одобрения администратора."), status_code=202)

    @app.get("/api/security/access-requests")
    def access_requests(request: Request) -> Response:
        if not _auth_disabled() and not _is_admin(request):
            return JSONResponse({"status": "forbidden", "requests": []}, status_code=403)
        items = [{"id": key, **value} for key, value in _load_requests().items()]
        return JSONResponse({"status": "ok", "requests": items})

    @app.post("/api/security/access-requests/{request_id}/approve")
    def approve(request_id: str, request: Request) -> Response:
        if not _auth_disabled() and not _is_admin(request):
            return JSONResponse({"status": "forbidden"}, status_code=403)
        requests = _load_requests()
        entry = requests.get(request_id)
        if not entry:
            return JSONResponse({"status": "not_found", "request_id": request_id}, status_code=404)
        username = _clean(str(entry.get("username", "")))
        temporary_password = f"SA-{secrets.token_urlsafe(9)}"
        users = _load_users()
        existing = users.get(username, {}) if isinstance(users.get(username), dict) else {}
        existing.update({"password_hash": hash_password(temporary_password), "active": True, "role": "user", "must_change_password": True, "approved_at": int(time.time())})
        users[username] = existing
        entry.update({"status": "approved", "approved_at": int(time.time())})
        _save_users(users)
        _save_requests(requests)
        return JSONResponse({"status": "ok", "request_id": request_id, "username": username, "temporary_password": temporary_password})

    @app.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request) -> Response:
        username = _session_username(request)
        if not username:
            return RedirectResponse("/login?next=/change-password", status_code=303)
        return HTMLResponse(_change_html(username, ""))

    @app.post("/change-password")
    async def change_password(request: Request) -> Response:
        username = _session_username(request)
        if not username:
            return RedirectResponse("/login?next=/change-password", status_code=303)
        form = parse_qs((await request.body()).decode("utf-8"))
        current = (form.get("current_password") or [""])[0]
        new_password = (form.get("new_password") or [""])[0]
        users = _load_users()
        user = users.get(username, {})
        if not verify_password(current, str(user.get("password_hash", ""))):
            return HTMLResponse(_change_html(username, "Текущий пароль неверный"), status_code=401)
        if len(new_password) < MIN_PASSWORD_LENGTH:
            return HTMLResponse(_change_html(username, f"Минимум {MIN_PASSWORD_LENGTH} символов"), status_code=400)
        user.update({"password_hash": hash_password(new_password), "must_change_password": False})
        _save_users(users)
        return RedirectResponse("/", status_code=303)

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        return {"status": "ok" if username else "anonymous", "authenticated": bool(username), "username": username}

    @app.get("/startup")
    def startup() -> dict[str, str]:
        return {"status": "ok", "app": "SharipovAI OS"}


def _auth_disabled() -> bool:
    return os.getenv("SHARIPOVAI_DISABLE_AUTH", "0").lower() in {"1", "true", "yes"}


def _data_dir() -> Path:
    return Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))


def _env_path(primary: str, legacy: str, default: str) -> Path:
    return Path(os.getenv(primary) or os.getenv(legacy) or str(_data_dir() / default))


def _users_file() -> Path:
    return _env_path("SHARIPOVAI_USERS_FILE", "AUTH_USERS_FILE", "users.json")


def _requests_file() -> Path:
    return _env_path("SHARIPOVAI_ACCESS_REQUESTS_FILE", "AUTH_ACCESS_REQUESTS_FILE", "access_requests.json")


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_users() -> dict[str, Any]:
    data = _load_json(_users_file(), {})
    if isinstance(data, dict) and isinstance(data.get("users"), dict):
        return data["users"]
    return data if isinstance(data, dict) else {}


def _save_users(data: dict[str, Any]) -> None:
    _write_json(_users_file(), data)


def _load_requests() -> dict[str, Any]:
    data = _load_json(_requests_file(), {})
    if isinstance(data, list):
        return {str(item.get("id", i)): item for i, item in enumerate(data) if isinstance(item, dict)}
    return data if isinstance(data, dict) else {}


def _save_requests(data: dict[str, Any]) -> None:
    _write_json(_requests_file(), data)


def _clean(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _auth_secret() -> str:
    configured = os.getenv("AUTH_SECRET", "").strip()
    if configured:
        return configured
    return hashlib.sha256(f"{os.getenv('ADMIN_PASSWORD','')}:{os.getenv('BOT_TOKEN','')}:sharipovai".encode()).hexdigest()


def _make_session(username: str) -> str:
    payload = f"{_clean(username)}:{int(time.time())}:{secrets.token_urlsafe(12)}"
    signature = hmac.new(_auth_secret().encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload.encode() + b"." + signature).decode()


def _session_username(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw.encode())
        payload, signature = decoded.rsplit(b".", 1)
        expected = hmac.new(_auth_secret().encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        username, issued, _ = payload.decode().split(":", 2)
        if int(time.time()) - int(issued) > SESSION_TTL_SECONDS:
            return None
        return _clean(username)
    except Exception:
        return None


def _valid_credentials(username: str, password: str) -> bool:
    user = _load_users().get(_clean(username))
    if isinstance(user, dict):
        return bool(user.get("active", True)) and str(user.get("role", "user")) in {"admin", "user"} and verify_password(password, str(user.get("password_hash", "")))
    admin_user = _clean(os.getenv("ADMIN_USERNAME", "admin"))
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    return bool(admin_password and _clean(username) == admin_user and hmac.compare_digest(password, admin_password))


def _is_admin(request: Request) -> bool:
    username = _session_username(request)
    if not username:
        return False
    if username == _clean(os.getenv("ADMIN_USERNAME", "admin")):
        return True
    user = _load_users().get(username, {})
    return isinstance(user, dict) and user.get("role") == "admin" and bool(user.get("active", True))


def _is_production() -> bool:
    return bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("PRODUCTION"))


def _safe_next(value: str | None) -> str:
    value = value or "/"
    return value if value.startswith("/") and not value.startswith("//") else "/"


def _login_html(next_url: str, error: str) -> str:
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Вход в SharipovAI</title></head><body><main><h1>Вход в SharipovAI</h1><p>{escape(error)}</p><form method="post" action="/login"><input type="hidden" name="next" value="{escape(next_url)}"><label>Логин<input name="username" required></label><label>Пароль<input type="password" name="password" required></label><button type="submit">Войти</button></form><h2>Запросить доступ</h2><form method="post" action="/register"><label>Логин<input name="username" required></label><label>Контакт<input name="contact"></label><label>Причина<input name="reason"></label><button type="submit">Запросить доступ</button></form></main></body></html>'''


def _result_html(message: str) -> str:
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'></head><body><h1>{escape(message)}</h1><a href='/login'>Вернуться ко входу</a></body></html>"


def _change_html(username: str, error: str) -> str:
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'></head><body><h1>Смена пароля</h1><p>{escape(error)}</p><p>{escape(username)}</p><form method='post'><input type='password' name='current_password' required><input type='password' name='new_password' minlength='{MIN_PASSWORD_LENGTH}' required><button>Сохранить</button></form></body></html>"


app = create_app()
