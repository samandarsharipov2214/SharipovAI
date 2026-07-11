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
from .evidence_recorder_middleware import install_evidence_recorder_middleware
from .policy_guard_middleware import install_policy_guard_middleware
from .routes import router
from .user_admin import hash_password, verify_password

SESSION_COOKIE = "sharipovai_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 14)))
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "12"))


def create_app(runner_factory: Callable[[], SharipovAIRunner] | None = None) -> FastAPI:
    app_instance = FastAPI(title="SharipovAI OS", docs_url=None if _is_production() else "/docs", redoc_url=None)
    app_instance.state.runner_factory = runner_factory or SharipovAIRunner
    app_instance.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app_instance.include_router(router)
    _install_feature_apis(app_instance)
    _install_auth_entrypoints(app_instance)
    _install_auth_guard(app_instance)
    install_evidence_recorder_middleware(app_instance)
    install_policy_guard_middleware(app_instance)
    _install_public_entrypoints(app_instance)
    return app_instance


def _install_feature_apis(app_instance: FastAPI) -> None:
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
            getattr(module, function_name)(app_instance)
        except Exception as exc:
            _install_feature_error_endpoint(app_instance, module_name, exc)


def _install_feature_error_endpoint(app_instance: FastAPI, module_name: str, exc: Exception) -> None:
    error_key = module_name.replace(".", "_").replace("-", "_")

    @app_instance.get(f"/api/startup-warning/{error_key}")
    def startup_warning() -> dict[str, Any]:
        return {"status": "warning", "module": module_name, "error": f"{type(exc).__name__}: {exc}"}


def _install_auth_guard(app_instance: FastAPI) -> None:
    public_exact = {"/", "/login", "/register", "/logout", "/health", "/api/health", "/startup"}
    public_prefixes = ("/static/", "/docs", "/openapi.json", "/api/security/status")

    @app_instance.middleware("http")
    async def auth_guard(request: Request, call_next):
        if _auth_disabled():
            return await call_next(request)
        path = request.url.path
        if path in public_exact or any(path.startswith(prefix) for prefix in public_prefixes):
            return await call_next(request)
        if _session_username(request):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"status": "unauthorized", "detail": "authentication required"}, status_code=401)
        return RedirectResponse(url=f"/login?next={_safe_next_url(path)}", status_code=303)


def _install_auth_entrypoints(app_instance: FastAPI) -> None:
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
            _record_security_event("failed_login", username or "anonymous", request, {"reason": "bad_credentials_or_inactive"})
            return HTMLResponse(_login_page_html(next_url=next_url, error="Неверный логин, пароль или доступ ещё не одобрен"), status_code=401)
        user = _user_record(_load_users(), username)
        target = "/change-password" if user and user.get("must_change_password") else next_url
        response = RedirectResponse(url=target, status_code=303)
        response.set_cookie(SESSION_COOKIE, _make_session(username), max_age=SESSION_TTL_SECONDS, httponly=True, secure=_is_production(), samesite="lax", path="/")
        _record_security_event("login", username, request)
        return response

    @app_instance.get("/logout")
    def logout(request: Request) -> Response:
        username = _session_username(request) or "anonymous"
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        _record_security_event("logout", username, request)
        return response

    @app_instance.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request) -> Response:
        username = _session_username(request)
        if not username:
            return RedirectResponse(url="/login?next=/change-password", status_code=303)
        return HTMLResponse(_change_password_html(username=username, error=""))

    @app_instance.post("/change-password")
    async def change_password_submit(request: Request) -> Response:
        username = _session_username(request)
        if not username:
            return RedirectResponse(url="/login?next=/change-password", status_code=303)
        form = parse_qs((await request.body()).decode("utf-8"))
        current = (form.get("current_password") or [""])[0]
        new_password = (form.get("new_password") or [""])[0]
        repeat = (form.get("repeat_password") or [new_password])[0]
        users = _load_users()
        user = _user_record(users, username)
        if not user or not verify_password(current, str(user.get("password_hash", ""))):
            _record_security_event("password_change_failed", username, request, {"reason": "bad_current_password"})
            return HTMLResponse(_change_password_html(username=username, error="Текущий пароль неверный"), status_code=401)
        if len(new_password) < MIN_PASSWORD_LENGTH or new_password != repeat:
            return HTMLResponse(_change_password_html(username=username, error=f"Новый пароль должен совпадать и быть не короче {MIN_PASSWORD_LENGTH} символов"), status_code=400)
        user["password_hash"] = hash_password(new_password)
        user["must_change_password"] = False
        user["password_changed_at"] = int(time.time())
        _save_users(users)
        _record_security_event("password_changed", username, request)
        return RedirectResponse(url="/", status_code=303)

    @app_instance.post("/register")
    async def register(request: Request) -> HTMLResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        contact = ((form.get("contact") or [""])[0]).strip()
        reason = ((form.get("reason") or [""])[0]).strip()
        if not username:
            return HTMLResponse(_register_result_html("Нужен логин."), status_code=400)
        requests = _load_access_requests()
        if any(str(item.get("username", "")) == username for item in requests.values() if isinstance(item, dict)):
            return HTMLResponse(_register_result_html("Пользователь или заявка уже существует."), status_code=409)
        request_id = f"REQ-{int(time.time())}-{secrets.token_hex(3)}"
        requests[request_id] = {
            "username": username,
            "contact": contact,
            "reason": reason,
            "status": "pending_security_review",
            "created_at": int(time.time()),
        }
        _save_access_requests(requests)
        _record_security_event("access_request_created", username, request, {"request_id": request_id})
        return HTMLResponse(_register_result_html("Запрос доступа отправлен. Ожидайте проверки безопасности."), status_code=202)

    @app_instance.get("/api/security/access-requests")
    def access_requests(request: Request) -> dict[str, Any]:
        if not _auth_disabled() and not _is_admin_request(request):
            return {"status": "forbidden", "requests": []}
        return {"status": "ok", "requests": [{"id": key, **value} for key, value in _load_access_requests().items()]}

    @app_instance.post("/api/security/access-requests/{request_id}/approve")
    def approve_access_request(request_id: str, request: Request) -> dict[str, Any]:
        admin = _session_username(request) or ("local-test-admin" if _auth_disabled() else "")
        if not admin or (not _auth_disabled() and not _is_admin_request(request)):
            return {"status": "forbidden"}
        requests = _load_access_requests()
        entry = requests.get(request_id)
        if not isinstance(entry, dict):
            return {"status": "not_found", "request_id": request_id}
        users = _load_users()
        username = _clean_username(str(entry.get("username", "")))
        temporary_password = secrets.token_urlsafe(12)
        users[username] = {
            "password_hash": hash_password(temporary_password),
            "created_at": int(time.time()),
            "active": True,
            "role": "user",
            "must_change_password": True,
            "approved_at": int(time.time()),
        }
        entry["status"] = "approved"
        entry["approved_by"] = admin
        _save_users(users)
        _save_access_requests(requests)
        _record_security_event("access_request_approved", admin, request, {"request_id": request_id})
        return {"status": "ok", "request_id": request_id, "temporary_password": temporary_password}

    @app_instance.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        if not username:
            return {"status": "anonymous", "authenticated": False}
        user = _user_record(_load_users(), username) or {}
        return {"status": "ok", "authenticated": True, "username": username, "role": user.get("role", "user")}

    @app_instance.get("/api/security/status")
    def security_status(request: Request) -> dict[str, Any]:
        return {"status": "ok", "authenticated": bool(_session_username(request)), "production": _is_production(), "auth_secret_configured": bool(os.getenv("AUTH_SECRET", "").strip()), "persistent_data_dir": str(_data_dir())}


def _install_public_entrypoints(app_instance: FastAPI) -> None:
    if getattr(app_instance.state, "public_entrypoints_installed", False):
        return
    app_instance.state.public_entrypoints_installed = True

    @app_instance.get("/startup")
    def startup() -> dict[str, str]:
        return {"status": "ok", "app": "SharipovAI OS"}


def _auth_disabled() -> bool:
    return os.getenv("SHARIPOVAI_DISABLE_AUTH", "1").strip().lower() in {"1", "true", "yes", "on"}


def _clean_username(username: str) -> str:
    return username.strip().lower().replace(" ", "_")


def _data_dir() -> Path:
    return Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))


def _users_file() -> Path:
    return Path(os.getenv("AUTH_USERS_FILE") or os.getenv("SHARIPOVAI_USERS_FILE") or str(_data_dir() / "users.json"))


def _access_requests_file() -> Path:
    return Path(os.getenv("AUTH_ACCESS_REQUESTS_FILE") or os.getenv("SHARIPOVAI_ACCESS_REQUESTS_FILE") or str(_data_dir() / "access_requests.json"))


def _security_events_file() -> Path:
    return Path(os.getenv("AUTH_SECURITY_EVENTS_FILE") or os.getenv("SHARIPOVAI_SECURITY_EVENTS_FILE") or str(_data_dir() / "security_events.jsonl"))


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _load_users() -> dict[str, Any]:
    users = _load_json(_users_file(), {})
    if isinstance(users, dict) and isinstance(users.get("users"), dict):
        return users["users"]
    return users if isinstance(users, dict) else {}


def _save_users(users: dict[str, Any]) -> None:
    _write_json(_users_file(), users)


def _load_access_requests() -> dict[str, Any]:
    data = _load_json(_access_requests_file(), {})
    return data if isinstance(data, dict) else {}


def _save_access_requests(requests: dict[str, Any]) -> None:
    _write_json(_access_requests_file(), requests)


def _user_record(users: dict[str, Any], username: str) -> dict[str, Any] | None:
    value = users.get(_clean_username(username))
    return value if isinstance(value, dict) else None


def _auth_secret() -> str:
    configured = os.getenv("AUTH_SECRET", "").strip()
    if configured:
        return configured
    seed = f"{os.getenv('ADMIN_PASSWORD', '')}:{os.getenv('BOT_TOKEN', '')}:sharipovai"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _valid_credentials(username: str, password: str) -> bool:
    username = _clean_username(username)
    user = _user_record(_load_users(), username)
    if user:
        if not bool(user.get("active", True)) or str(user.get("role", "user")) not in {"admin", "user"}:
            return False
        return verify_password(password, str(user.get("password_hash", "")))
    admin_username = _clean_username(os.getenv("ADMIN_USERNAME", "admin"))
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    return bool(admin_password and username == admin_username and hmac.compare_digest(password, admin_password))


def _is_admin_request(request: Request) -> bool:
    username = _session_username(request)
    if not username:
        return False
    if username == _clean_username(os.getenv("ADMIN_USERNAME", "admin")):
        return True
    user = _user_record(_load_users(), username) or {}
    return str(user.get("role", "")).lower() == "admin" and bool(user.get("active", True))


def _make_session(username: str) -> str:
    issued = str(int(time.time()))
    nonce = secrets.token_urlsafe(16)
    payload = f"{_clean_username(username)}:{issued}:{nonce}"
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
        username, issued, _nonce = payload.decode().split(":", 2)
        if int(time.time()) - int(issued) > SESSION_TTL_SECONDS:
            return None
        user = _user_record(_load_users(), username)
        if user and (not bool(user.get("active", True)) or str(user.get("role", "")) not in {"admin", "user"}):
            return None
        return _clean_username(username)
    except Exception:
        return None


def _safe_next_url(next_url: str | None) -> str:
    value = (next_url or "/").strip()
    return value if value.startswith("/") and not value.startswith("//") else "/"


def _is_production() -> bool:
    return bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}


def _record_security_event(event: str, username: str, request: Request | None = None, metadata: dict[str, Any] | None = None) -> None:
    record = {"event": event, "username": _clean_username(username), "time": int(time.time()), "ip": request.client.host if request and request.client else "unknown", "user_agent": request.headers.get("user-agent", "") if request else "", "metadata": metadata or {}}
    path = _security_events_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _login_page_html(*, next_url: str, error: str = "") -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Вход в SharipovAI</title><style>body{{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{max-width:420px;margin:10vh auto;padding:24px;background:#111827;border-radius:24px;border:1px solid #263245}}input,textarea,button{{box-sizing:border-box;width:100%;padding:13px;margin:8px 0;border-radius:12px;border:1px solid #334155}}button{{background:#38bdf8;color:#02111f;font-weight:900}}.error{{color:#fca5a5}}</style></head><body><main><h1>Вход в SharipovAI</h1>{error_html}<form method="post" action="/login"><input type="hidden" name="next" value="{escape(next_url)}"><label>Логин<input name="username" autocomplete="username" required></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><button type="submit">Войти</button></form><hr><h2>Запросить доступ</h2><form method="post" action="/register"><label>Новый логин<input name="username" required></label><label>Контакт<input name="contact"></label><label>Причина<textarea name="reason"></textarea></label><button type="submit">Запросить доступ</button></form></main></body></html>"""


def _change_password_html(*, username: str, error: str = "") -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return f"<!doctype html><html lang='ru'><meta name='viewport' content='width=device-width,initial-scale=1'><body><main><h1>Смена пароля</h1><p>{escape(username)}</p>{error_html}<form method='post' action='/change-password'><input name='current_password' type='password' placeholder='Текущий пароль' required><input name='new_password' type='password' minlength='{MIN_PASSWORD_LENGTH}' placeholder='Новый пароль' required><input name='repeat_password' type='password' minlength='{MIN_PASSWORD_LENGTH}' placeholder='Повторите пароль' required><button type='submit'>Сменить пароль</button></form></main></body></html>"


def _register_result_html(message: str) -> str:
    return f"<!doctype html><html lang='ru'><meta name='viewport' content='width=device-width,initial-scale=1'><body><main><h1>SharipovAI</h1><p>{escape(message)}</p><a href='/login'>Назад</a></main></body></html>"


app = create_app()

__all__ = ["app", "create_app", "_clean_username", "_load_users", "_login_page_html", "_record_security_event", "_safe_next_url", "_session_username", "_valid_credentials"]