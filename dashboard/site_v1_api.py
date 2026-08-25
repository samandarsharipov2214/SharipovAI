"""Canonical, password-safe Site V1 access request API."""
from __future__ import annotations
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from .auth_saas import ensure_same_origin
from .db_saas import SessionLocal
from .models_saas import AccessRequest, User
from .user_admin import hash_password

class SiteV1RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=5, max_length=320)
    contact: str = Field(min_length=2, max_length=320)
    password: str = Field(min_length=12, max_length=200)
    password_confirmation: str = Field(min_length=12, max_length=200)
    reason: str = Field(default="", max_length=2000)
    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: str) -> str:
        value = value.lower().strip()
        if value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email")
        return value

def install_site_v1_api(app: FastAPI) -> None:
    if getattr(app.state, "site_v1_api_installed", False): return
    app.state.site_v1_api_installed = True
    @app.post("/api/site-v1/access-requests")
    def register(payload: SiteV1RegisterRequest, request: Request) -> dict[str, str]:
        ensure_same_origin(request)
        if payload.password != payload.password_confirmation:
            raise HTTPException(422, detail={"status": "password_mismatch"})
        db = SessionLocal()
        try:
            if db.scalar(select(User).where(User.email == payload.email)):
                raise HTTPException(409, detail={"status": "already_exists"})
            user = User(email=payload.email, display_name=payload.name, password_hash=hash_password(payload.password), is_active=False, role="user")
            db.add(user); db.flush()
            db.add(AccessRequest(user_id=user.id, contact=payload.contact, reason=payload.reason))
            db.commit()
            return {"status": "pending_approval", "message": "Заявка отправлена. После одобрения вы сможете войти."}
        finally: db.close()
