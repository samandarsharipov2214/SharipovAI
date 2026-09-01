"""JWT cookie authentication for the SharipovAI SaaS frontend."""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import jwt
from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db_saas import SessionLocal
from .models_saas import AccessRequest, Subscription, User
from .settings_saas import get_saas_settings
from .user_admin import hash_password, verify_password

_ACCESS_TOKEN_KIND = "access"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str | None = Field(default=None, max_length=320)
    username: str | None = Field(default=None, max_length=64)
    password: str = Field(min_length=1, max_length=200, repr=False)

    @model_validator(mode="after")
    def require_identifier(self) -> "LoginRequest":
        if not (self.email or self.username):
            raise ValueError("email or username required")
        return self


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=5, max_length=320)
    contact: str = Field(min_length=2, max_length=320)
    password: str = Field(min_length=12, max_length=200, repr=False)
    password_confirmation: str = Field(min_length=12, max_length=200, repr=False)
    reason: str = Field(default="", max_length=2000)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("invalid email")
        return normalized

    @model_validator(mode="after")
    def passwords_match(self) -> RegistrationRequest:
        if self.password != self.password_confirmation:
            raise ValueError("passwords do not match")
        return self


class AuthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    authenticated: bool
    user: dict[str, Any] | None = None


settings = get_saas_settings()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_by_email(email: str):
    return select(User).where(func.lower(User.email) == normalize_email(email))


def _registration_payload(raw_payload: Any) -> RegistrationRequest:
    try:
        return RegistrationRequest.model_validate(raw_payload)
    except ValidationError:
        raise HTTPException(
            status_code=422,
            detail={"status": "invalid_registration", "message": "Проверьте поля регистрации."},
        ) from None


def _login_payload(raw_payload: Any) -> LoginRequest:
    try:
        return LoginRequest.model_validate(raw_payload)
    except ValidationError:
        raise HTTPException(
            status_code=422,
            detail={"status": "invalid_login", "message": "Проверьте формат данных входа."},
        ) from None


def _login_identifier(payload: LoginRequest) -> str:
    return str(payload.email or payload.username or "").strip()


def _legacy_owner_login_response(identifier: str, password: str) -> JSONResponse | None:
    """Authenticate the existing production owner via username session.

    Site V1 posts JSON to /api/auth/login. The live owner account lives in the
    legacy users store (username/password), not necessarily in saas_users.
    Never invent credentials: only the existing verifier is used.
    """
    # Owner usernames are not emails. Skip the legacy store for email-shaped
    # identifiers so a missing SaaS user does not import dashboard.app.
    if "@" in identifier:
        return None
    from .app import (
        SESSION_COOKIE,
        SESSION_TTL_SECONDS,
        _clean_username,
        _is_production,
        _load_users,
        _make_session,
        _user_record,
        _valid_credentials,
    )

    username = _clean_username(identifier)
    if not username or not _valid_credentials(username, password):
        return None
    record = _user_record(_load_users(), username) or {}
    role = str(record.get("role") or "").strip().lower()
    admin_username = _clean_username(os.getenv("ADMIN_USERNAME", "admin"))
    if role not in {"admin", "user"}:
        role = "admin" if username == admin_username else "user"
    user = {
        "id": username,
        "email": username,
        "display_name": username,
        "role": role,
    }
    response = JSONResponse(
        AuthResponse(status="ok", authenticated=True, user=user).model_dump()
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=_make_session(username),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_is_production(),
        samesite="lax",
        path="/",
    )
    return response


def ensure_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return
    host = request.headers.get("host", "").split(",", 1)[0].strip().lower()
    request_scheme = request.url.scheme.lower()
    try:
        parsed = urlsplit(origin)
    except ValueError:
        parsed = None
    if (
        not host
        or parsed is None
        or parsed.scheme.lower() not in {"http", "https"}
        or parsed.scheme.lower() != request_scheme
        or parsed.netloc.lower() != host
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
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
        if not payload:
            return None
        db = SessionLocal()
        try:
            user = db.scalar(_user_by_email(str(payload["sub"])))
            if not user or not user.is_active:
                return None
            return user.email
        finally:
            db.close()
    return _legacy_session_identity(request)


def get_current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(settings.auth_cookie_name, "")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user = db.scalar(_user_by_email(str(payload["sub"])))
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
    # Upgraded browsers can still carry the canonical legacy session cookie.
    # Logout must end both authentication mechanisms, not reveal it by fallback.
    response.delete_cookie("sharipovai_session", path="/")


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


def _access_request_rows(db: Session) -> list[dict[str, Any]]:
    """Return the canonical approval queue with safe, display-ready fields."""
    rows = db.scalars(select(AccessRequest).order_by(AccessRequest.created_at.desc())).all()
    users = {user.id: user for user in db.scalars(select(User).where(User.id.in_([row.user_id for row in rows]))).all()} if rows else {}
    return [{
        "id": row.id, "user_id": row.user_id,
        "email": users[row.user_id].email if row.user_id in users else "",
        "name": users[row.user_id].display_name if row.user_id in users else "",
        "contact": row.contact, "reason": row.reason, "status": row.status,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


def _decide_access_request(db: Session, request_id: str, reviewer: str, decision: str) -> None:
    """Atomically reserve a pending request for exactly one terminal decision."""
    now = datetime.now(UTC)
    changed = db.execute(
        update(AccessRequest)
        .where(AccessRequest.id == request_id, AccessRequest.status == "pending")
        .values(status=decision, reviewed_at=now, reviewed_by=reviewer)
    )
    if changed.rowcount != 1:
        existing = db.get(AccessRequest, request_id)
        if existing is None:
            raise HTTPException(status_code=404, detail={"status": "not_found"})
        raise HTTPException(status_code=409, detail={"status": "already_decided", "decision": existing.status})
    active = decision == "approved"
    user_changed = db.execute(update(User).where(User.id == db.get(AccessRequest, request_id).user_id).values(is_active=active))
    if user_changed.rowcount != 1:
        raise HTTPException(status_code=409, detail={"status": "user_missing"})


def install_saas_auth_api(app: FastAPI) -> None:
    if getattr(app.state, "saas_auth_api_installed", False):
        return
    app.state.saas_auth_api_installed = True

    @app.post("/api/auth/register", response_model=AuthResponse)
    async def register(request: Request, raw_payload: Any = Body(...)) -> AuthResponse:
        ensure_same_origin(request)
        payload = _registration_payload(raw_payload)
        db = SessionLocal()
        try:
            email = normalize_email(payload.email)
            existing = db.scalar(_user_by_email(email))
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={"status": "already_exists", "message": "Пользователь уже существует."},
                )
            user = User(
                email=email,
                display_name=payload.name.strip(),
                password_hash=hash_password(payload.password),
                is_active=False,
                role="user",
                free_messages_limit=settings.free_messages_per_month,
            )
            db.add(user)
            db.flush()
            db.add(
                AccessRequest(
                    user_id=user.id,
                    contact=payload.contact.strip(),
                    reason=payload.reason.strip(),
                )
            )
            db.commit()
            return AuthResponse(
                status="pending_approval",
                authenticated=False,
                user=serialize_user(user),
            )
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"status": "already_exists", "message": "Пользователь уже существует."},
            ) from None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.post("/api/auth/login", response_model=AuthResponse)
    async def login(request: Request, raw_payload: Any = Body(...)) -> AuthResponse:
        ensure_same_origin(request)
        payload = _login_payload(raw_payload)
        identifier = _login_identifier(payload)
        db = SessionLocal()
        try:
            user = db.scalar(_user_by_email(normalize_email(identifier)))
            if user is None:
                legacy = _legacy_owner_login_response(identifier, payload.password)
                if legacy is not None:
                    return legacy
                raise HTTPException(
                    status_code=401,
                    detail={"status": "invalid_credentials", "message": "Неверный email или пароль."},
                )
            if not verify_password(payload.password, user.password_hash):
                raise HTTPException(
                    status_code=401,
                    detail={"status": "invalid_credentials", "message": "Неверный email или пароль."},
                )
            if not user.is_active:
                access_request = db.scalar(
                    select(AccessRequest).where(AccessRequest.user_id == user.id)
                )
                if access_request and access_request.status == "rejected":
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "status": "access_rejected",
                            "message": "Заявка на доступ не одобрена.",
                        },
                    )
                raise HTTPException(
                    status_code=403,
                    detail={
                        "status": "pending_approval",
                        "message": "Заявка ещё ожидает одобрения.",
                    },
                )
            _ensure_free_subscription(db, user)
            db.commit()
            response = JSONResponse(
                AuthResponse(status="ok", authenticated=True, user=serialize_user(user)).model_dump()
            )
            set_auth_cookie(response, issue_access_token(user))
            return response
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.get("/api/auth/access-requests")
    async def list_access_requests(request: Request) -> dict[str, Any]:
        from .admin_guard import require_admin

        require_admin(request)
        db = SessionLocal()
        try:
            return {"status": "ok", "requests": _access_request_rows(db)}
        finally:
            db.close()

    @app.get("/api/security/access-requests")
    async def security_access_requests(request: Request) -> dict[str, Any]:
        """Compatibility URL, backed by the one canonical SaaS approval queue."""
        return await list_access_requests(request)

    @app.post("/api/auth/access-requests/{request_id}/approve")
    async def approve_access_request(request_id: str, request: Request) -> dict[str, str]:
        from .admin_guard import require_admin

        ensure_same_origin(request)
        reviewer = require_admin(request)
        db = SessionLocal()
        try:
            _decide_access_request(db, request_id, reviewer, "approved")
            db.commit()
            return {"status": "approved", "request_id": request_id}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.post("/api/security/access-requests/{request_id}/approve")
    async def security_approve_access_request(request_id: str, request: Request) -> dict[str, str]:
        return await approve_access_request(request_id, request)

    @app.post("/api/auth/access-requests/{request_id}/reject")
    async def reject_access_request(request_id: str, request: Request) -> dict[str, str]:
        from .admin_guard import require_admin

        ensure_same_origin(request)
        reviewer = require_admin(request)
        db = SessionLocal()
        try:
            _decide_access_request(db, request_id, reviewer, "rejected")
            db.commit()
            return {"status": "rejected", "request_id": request_id}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.post("/api/security/access-requests/{request_id}/reject")
    async def security_reject_access_request(request_id: str, request: Request) -> dict[str, str]:
        return await reject_access_request(request_id, request)

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
