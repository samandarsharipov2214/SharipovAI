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
        ("dashboard.bot_communication_api", "install_bot_communication_api"),
        ("dashboard.autonomous_learning_api", "install_autonomous_learning_api"),
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
            secure=False,
            samesite="lax",
        )
        _record_security_event("login", username, request)
        return response

    @app_instance.get("/logout")
    def logout(request: Request) -> Response:
        username = _session_username(request) or "anonymous"
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        _record_security_event("logout", username, request)
        return response

    @app_instance.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request) -> HTMLResponse:
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
        users = _load_users()
        user = _user_record(users, username)
        if not user or not verify_password(current, str(user.get("password_hash", ""))):
            _record_security_event("password_change_failed", username, request, {"reason": "bad_current_password"})
            return HTMLResponse(_change_password_html(username=username, error="Текущий пароль неверный"), status_code=401)
        if len(new_password) < 8:
            return HTMLResponse(_change_password_html(username=username, error="Новый пароль должен быть не короче 8 символов"), status_code=400)
        user["password_hash"] = hash_password(new_password)
        user["must_change_password"] = False
        _save_users(users)
        _record_security_event("password_changed", username, request)
        return RedirectResponse(url="/", status_code=303)

    @app_instance.post("/register")
    async def register(request: Request) -> HTMLResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        username = _clean_username((form.get("username") or [""])[0])
        password = (form.get("password") or [""])[0]
        users = _load_users()
        if not username or len(password) < 8:
            return HTMLResponse(_register_result_html("Запрос отклонён: нужен логин и пароль от 8 символов."), status_code=400)
        if _user_record(users, username):
            return HTMLResponse(_register_result_html("Пользователь уже существует или запрос уже был создан."), status_code=409)
        create_user(username, password, role="pending", must_change_password=False)
        requests = _load_access_requests()
        request_id = f"REQ-{int(time.time())}-{secrets.token_hex(3)}"
        requests[request_id] = {"username": username, "status": "pending", "created_at": int(time.time())}
        _save_access_requests(requests)
        _record_security_event("access_request_created", username, request, {"request_id": request_id})
        return HTMLResponse(_register_result_html("Запросить доступ: заявка создана и ждёт approval администратора."))

    @app_instance.get("/api/security/access-requests")
    def access_requests(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        if not username:
            return {"status": "unauthorized", "requests": []}
        return {"status": "ok", "requests": [{"id": key, **value} for key, value in _load_access_requests().items()]}

    @app_instance.post("/api/security/access-requests/{request_id}/approve")
    def approve_access_request(request_id: str, request: Request) -> dict[str, Any]:
        username = _session_username(request)
        if not username:
            return {"status": "unauthorized"}
        requests = _load_access_requests()
        entry = requests.get(request_id)
        if not entry:
            return {"status": "not_found", "request_id": request_id}
        users = _load_users()
        user = _user_record(users, str(entry.get("username", "")))
        if user:
            user["role"] = "user"
        entry["status"] = "approved"
        _save_users(users)
        _save_access_requests(requests)
        _record_security_event("access_request_approved", username, request, {"request_id": request_id})
        return {"status": "ok", "request_id": request_id}

    @app_instance.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        username = _session_username(request)
        if not username:
            return {"status": "anonymous", "authenticated": False}
        users = _load_users()
        user = _user_record(users, username) or {}
        return {"status": "ok", "authenticated": True, "username": username, "role": user.get("role", "user")}


def _install_public_entrypoints(app_instance: FastAPI) -> None:
    """Install fallback public root and health routes for Render probes."""

    if getattr(app_instance.state, "public_entrypoints_installed", False):
        return
    app_instance.state.public_entrypoints_installed = True

    @app_instance.get("/startup")
    def startup() -> dict[str, str]:
        return {"status": "ok", "app": "SharipovAI OS"}


def _clean_username(username: str) -> str:
    return username.strip().lower().replace(" ", "_")


def _users_file() -> Path:
    return Path(os.getenv("SHARIPOVAI_USERS_FILE", "data/users.json"))


def _access_requests_file() -> Path:
    return Path(os.getenv("SHARIPOVAI_ACCESS_REQUESTS_FILE", "data/access_requests.json"))


def _security_events_file() -> Path:
    return Path(os.getenv("SHARIPOVAI_SECURITY_EVENTS_FILE", "data/security_events.jsonl"))


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_users() -> dict[str, Any]:
    return _load_json(_users_file(), {})


def _save_users(users: dict[str, Any]) -> None:
    _write_json(_users_file(), users)


def _load_access_requests() -> dict[str, Any]:
    return _load_json(_access_requests_file(), {})


def _save_access_requests(requests: dict[str, Any]) -> None:
    _write_json(_access_requests_file(), requests)


def _user_record(users: dict[str, Any], username: str) -> dict[str, Any] | None:
    return users.get(_clean_username(username))


def _auth_secret() -> str:
    return os.getenv("AUTH_SECRET", "dev-auth-secret-change-me")


def _valid_credentials(username: str, password: str) -> bool:
    username = _clean_username(username)
    users = _load_users()
    user = _user_record(users, username)
    if user:
        return verify_password(password, str(user.get("password_hash", "")))
    admin_username = _clean_username(os.getenv("ADMIN_USERNAME", "admin"))
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    return bool(admin_password and username == admin_username and hmac.compare_digest(password, admin_password))


def _make_session(username: str) -> str:
    ts = str(int(time.time()))
    payload = f"{_clean_username(username)}:{ts}"
    sig = hmac.new(_auth_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload.encode("utf-8") + b"." + sig).decode("ascii")


def _session_username(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
        payload, sig = decoded.rsplit(b".", 1)
        expected = hmac.new(_auth_secret().encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        username, ts = payload.decode("utf-8").split(":", 1)
        if int(time.time()) - int(ts) > SESSION_TTL_SECONDS:
            return None
        return _clean_username(username)
    except Exception:
        return None


def _safe_next_url(next_url: str | None) -> str:
    value = (next_url or "/").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _record_security_event(event: str, username: str, request: Request | None = None, metadata: dict[str, Any] | None = None) -> None:
    record = {
        "event": event,
        "username": _clean_username(username),
        "time": int(time.time()),
        "ip": request.client.host if request and request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "") if request else "",
        "metadata": metadata or {},
    }
    path = _security_events_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _login_page_html(*, next_url: str, error: str = "") -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI Login</title><style>body{{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{max-width:420px;margin:10vh auto;padding:24px;background:#111827;border-radius:24px;border:1px solid #263245}}input,button{{width:100%;padding:13px;margin:8px 0;border-radius:12px;border:1px solid #334155}}button{{background:#38bdf8;color:#02111f;font-weight:900}}.error{{color:#fca5a5}}</style></head><body><main><h1>SharipovAI Login</h1>{error_html}<form method="post" action="/login"><input type="hidden" name="next" value="{escape(next_url)}"><input name="username" placeholder="Логин" autocomplete="username"><input name="password" type="password" placeholder="Пароль" autocomplete="current-password"><button type="submit">Войти</button></form><hr><h2>Запросить доступ</h2><form method="post" action="/register"><input name="username" placeholder="Новый логин"><input name="password" type="password" placeholder="Пароль от 8 символов"><button type="submit">Запросить доступ</button></form></main></body></html>"""


def _change_password_html(*, username: str, error: str = "") -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Смена пароля</title></head><body><main><h1>Смена пароля</h1><p>{escape(username)}</p>{error_html}<form method="post" action="/change-password"><input name="current_password" type="password" placeholder="Текущий пароль"><input name="new_password" type="password" placeholder="Новый пароль"><button type="submit">Сменить пароль</button></form></main></body></html>"""


def _register_result_html(message: str) -> str:
    return f"<!doctype html><html lang='ru'><body><main><h1>SharipovAI</h1><p>{escape(message)}</p><a href='/login'>Назад</a></main></body></html>"


app = create_app()

__all__ = [
    "app",
    "create_app",
    "_clean_username",
    "_load_users",
    "_login_page_html",
    "_record_security_event",
    "_safe_next_url",
    "_session_username",
    "_valid_credentials",
]
