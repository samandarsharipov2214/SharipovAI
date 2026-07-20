"""JWT cookie authentication for the SharipovAI SaaS frontend."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_saas import SessionLocal
from .models_saas import Subscription, User
from .settings_saas import get_saas_settings
from .user_admin import hash_password, verify_password

_ACCESS_TOKEN_KIND = "access"


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=200)
    display_name: str = Field(default="", max_length=120)


class AuthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    authenticated: bool
    user: dict[str, Any] | None = None


settings = get_saas_settings()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def ensure_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return
    host = request.headers.get("host", "").split(",", 1)[0].strip().lower()
    if not origin.lower().startswith((f"http://{host}", f"https://{host}")):
        raise HTTPException(status_code=403, detail={"status": "cross_origin_blocked"})


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }


def issue_access_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.email,
        "role": user.role,
        "kind": _ACCESS_TOKEN_KIND,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("kind") != _ACCESS_TOKEN_KIND:
        return None
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None
    return payload


def _legacy_session_identity(request: Request) -> str | None:
    try:
        from .app import _session_username

        return _session_username(request)
    except Exception:
        return None


def resolve_authenticated_principal(request: Request) -> str | None:
    token = request.cookies.get(settings.auth_cookie_name, "")
    if token:
        payload = decode_access_token(token)
        if payload:
            return str(payload["sub"])
    return _legacy_session_identity(request)


def get_current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(settings.auth_cookie_name, "")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    stmt = select(User).where(User.email == normalize_email(str(payload["sub"])))
    user = db.scalar(stmt)
    if not user or not user.is_active:
        return None
    return user


def require_current_user(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})
    return user


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")


def _ensure_free_subscription(db: Session, user: User) -> None:
    if user.subscription:
        return
    db.add(
        Subscription(
            user=user,
            provider="stripe",
            plan_code="free",
            status="free",
        )
    )


def install_saas_auth_api(app: FastAPI) -> None:
    if getattr(app.state, "saas_auth_api_installed", False):
        return
    app.state.saas_auth_api_installed = True

    @app.post("/api/auth/register", response_model=AuthResponse)
    async def register(payload: AuthRequest, request: Request) -> AuthResponse:
        ensure_same_origin(request)
        db = SessionLocal()
        try:
            email = normalize_email(payload.email)
            existing = db.scalar(select(User).where(User.email == email))
            if existing:
                raise HTTPException(status_code=409, detail={"status": "already_exists", "message": "Пользователь уже существует."})
            user = User(
                email=email,
                display_name=payload.display_name.strip(),
                password_hash=hash_password(payload.password),
                free_messages_limit=settings.free_messages_per_month,
            )
            db.add(user)
            db.flush()
            _ensure_free_subscription(db, user)
            db.commit()
            response = JSONResponse(
                AuthResponse(status="ok", authenticated=True, user=serialize_user(user)).model_dump()
            )
            set_auth_cookie(response, issue_access_token(user))
            return response
        finally:
            db.close()

    @app.post("/api/auth/login", response_model=AuthResponse)
    async def login(payload: AuthRequest, request: Request) -> AuthResponse:
        ensure_same_origin(request)
        db = SessionLocal()
        try:
            email = normalize_email(payload.email)
            user = db.scalar(select(User).where(User.email == email))
            if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
                raise HTTPException(status_code=401, detail={"status": "invalid_credentials", "message": "Неверный email или пароль."})
            _ensure_free_subscription(db, user)
            db.commit()
            response = JSONResponse(
                AuthResponse(status="ok", authenticated=True, user=serialize_user(user)).model_dump()
            )
            set_auth_cookie(response, issue_access_token(user))
            return response
        finally:
            db.close()

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> dict[str, str]:
        ensure_same_origin(request)
        response = JSONResponse({"status": "ok"})
        clear_auth_cookie(response)
        return response

    @app.get("/api/auth/me", response_model=AuthResponse)
    async def me(request: Request) -> AuthResponse:
        db = SessionLocal()
        try:
            user = get_current_user(request, db)
            if user:
                return AuthResponse(status="ok", authenticated=True, user=serialize_user(user))
            principal = resolve_authenticated_principal(request)
            if principal:
                return AuthResponse(
                    status="ok",
                    authenticated=True,
                    user={"id": principal, "email": principal, "display_name": principal, "role": "admin"},
                )
            return AuthResponse(status="anonymous", authenticated=False, user=None)
        finally:
            db.close()


__all__ = [
    "clear_auth_cookie",
    "ensure_same_origin",
    "get_current_user",
    "install_saas_auth_api",
    "issue_access_token",
    "normalize_email",
    "require_current_user",
    "resolve_authenticated_principal",
    "serialize_user",
    "set_auth_cookie",
]
