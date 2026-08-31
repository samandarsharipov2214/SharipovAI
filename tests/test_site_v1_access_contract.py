from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import dashboard.admin_guard as admin_guard
import dashboard.auth_saas as auth_saas
from dashboard.models_saas import AccessRequest, Base, User
from dashboard.user_admin import verify_password

ROOT = Path(__file__).resolve().parents[1]
ORIGIN_HEADERS = {"host": "testserver", "origin": "http://testserver"}
PASSWORD = "correct-horse-battery-staple"


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _client(monkeypatch):
    sessions = _session_factory()
    monkeypatch.setattr(auth_saas, "SessionLocal", sessions)
    app = FastAPI()
    auth_saas.install_saas_auth_api(app)
    return TestClient(app), sessions


def _registration(**overrides):
    payload = {
        "name": "Ada Lovelace",
        "email": "ada@example.test",
        "contact": "@ada",
        "password": PASSWORD,
        "password_confirmation": PASSWORD,
        "reason": "AI research",
    }
    payload.update(overrides)
    return payload


def test_registration_uses_canonical_user_and_password_safe_metadata(monkeypatch):
    client, sessions = _client(monkeypatch)
    response = client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    assert response.json()["authenticated"] is False
    assert "set-cookie" not in response.headers
    with sessions() as db:
        users = db.scalars(select(User)).all()
        requests = db.scalars(select(AccessRequest)).all()
        assert len(users) == len(requests) == 1
        assert users[0].is_active is False
        assert users[0].role == "user"
        assert verify_password(PASSWORD, users[0].password_hash)
        assert PASSWORD not in users[0].password_hash
        assert requests[0].user_id == users[0].id
        assert requests[0].contact == "@ada"
        assert not hasattr(requests[0], "password")
        assert PASSWORD not in repr(requests[0])


def test_registration_validation_and_duplicate_are_fail_closed(monkeypatch):
    client, sessions = _client(monkeypatch)
    invalid_payloads = (
        _registration(email="not-an-email"),
        _registration(password="short", password_confirmation="short"),
        _registration(password_confirmation="different-long-password"),
        _registration(contact=""),
        _registration(name="x" * 121),
    )
    for payload in invalid_payloads:
        response = client.post("/api/auth/register", json=payload, headers=ORIGIN_HEADERS)
        assert response.status_code == 422
        assert payload["password"] not in response.text
        assert payload["password_confirmation"] not in response.text

    accepted = client.post(
        "/api/auth/register",
        json=_registration(email="Ada@Example.Test"),
        headers=ORIGIN_HEADERS,
    )
    assert accepted.status_code == 200
    duplicate = client.post(
        "/api/auth/register",
        json=_registration(email="ADA@EXAMPLE.TEST"),
        headers=ORIGIN_HEADERS,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["status"] == "already_exists"
    with sessions() as db:
        assert len(db.scalars(select(User)).all()) == 1
        assert len(db.scalars(select(AccessRequest)).all()) == 1


def test_registration_requires_name(monkeypatch):
    client, _sessions = _client(monkeypatch)
    response = client.post("/api/auth/register", json=_registration(name=""), headers=ORIGIN_HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["status"] == "invalid_registration"


def test_active_pending_and_rejected_accounts_cannot_register_again(monkeypatch):
    client, sessions = _client(monkeypatch)
    assert client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS).status_code == 200

    for account_state in ("pending", "active", "rejected"):
        with sessions() as db:
            user = db.scalar(select(User))
            access_request = db.scalar(select(AccessRequest))
            user.is_active = account_state == "active"
            access_request.status = "rejected" if account_state == "rejected" else "pending"
            db.commit()
        response = client.post(
            "/api/auth/register",
            json=_registration(email="ADA@EXAMPLE.TEST"),
            headers=ORIGIN_HEADERS,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["status"] == "already_exists"

    with sessions() as db:
        assert len(db.scalars(select(User)).all()) == 1
        assert len(db.scalars(select(AccessRequest)).all()) == 1


def test_concurrent_unique_collision_returns_stable_conflict_and_rolls_back(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)

    class CollisionSession(Session):
        def commit(self):
            raise IntegrityError("synthetic concurrent duplicate", {}, RuntimeError("unique"))

    collision_sessions = sessionmaker(bind=engine, class_=CollisionSession, expire_on_commit=False)
    inspection_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(auth_saas, "SessionLocal", collision_sessions)
    app = FastAPI()
    auth_saas.install_saas_auth_api(app)

    response = TestClient(app).post(
        "/api/auth/register",
        json=_registration(),
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "already_exists"
    assert PASSWORD not in response.text
    with inspection_sessions() as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(AccessRequest)) is None


def test_registration_rejects_cross_origin(monkeypatch):
    client, sessions = _client(monkeypatch)
    response = client.post(
        "/api/auth/register",
        json=_registration(),
        headers={"host": "testserver", "origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    with sessions() as db:
        assert db.scalar(select(User)) is None


def test_registration_treats_profile_metadata_as_text_and_never_echoes_password(monkeypatch):
    client, sessions = _client(monkeypatch)
    payload = _registration(
        name='<img src=x onerror="alert(1)">',
        contact="<script>alert(2)</script>",
        reason="<b>research</b>",
    )

    response = client.post("/api/auth/register", json=payload, headers=ORIGIN_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["user"]["display_name"] == payload["name"]
    assert PASSWORD not in response.text
    with sessions() as db:
        access_request = db.scalar(select(AccessRequest))
        assert access_request.contact == payload["contact"]
        assert access_request.reason == payload["reason"]


def test_registration_rolls_back_user_when_request_insert_fails(monkeypatch):
    client, sessions = _client(monkeypatch)

    def fail_access_request(**_kwargs):
        raise RuntimeError("synthetic metadata failure")

    monkeypatch.setattr(auth_saas, "AccessRequest", fail_access_request)
    try:
        response = client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)
    except RuntimeError:
        pass
    else:
        assert response.status_code == 500
    with sessions() as db:
        assert db.scalar(select(User)) is None


def test_login_contract_pending_wrong_approved_logout(monkeypatch):
    client, sessions = _client(monkeypatch)
    assert client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS).status_code == 200

    wrong = client.post(
        "/api/auth/login",
        json={"email": "ada@example.test", "password": "wrong-password-long-enough"},
        headers=ORIGIN_HEADERS,
    )
    assert wrong.status_code == 401
    unknown = client.post(
        "/api/auth/login",
        json={"email": "unknown@example.test", "password": "wrong"},
        headers=ORIGIN_HEADERS,
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"]["status"] == "invalid_credentials"
    malformed = client.post(
        "/api/auth/login",
        json={"email": "ada@example.test", "password": PASSWORD, "name": "unexpected"},
        headers=ORIGIN_HEADERS,
    )
    assert malformed.status_code == 422
    assert PASSWORD not in malformed.text
    pending = client.post(
        "/api/auth/login",
        json={"email": "ada@example.test", "password": PASSWORD},
        headers=ORIGIN_HEADERS,
    )
    assert pending.status_code == 403
    assert pending.json()["detail"]["status"] == "pending_approval"

    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "ada@example.test"))
        user.is_active = True
        db.commit()

    approved = client.post(
        "/api/auth/login",
        json={"email": "ada@example.test", "password": PASSWORD},
        headers=ORIGIN_HEADERS,
    )
    assert approved.status_code == 200
    assert approved.json()["authenticated"] is True
    cookie = approved.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=" in cookie
    assert f"max-age={auth_saas.settings.jwt_ttl_seconds}" in cookie
    logout = client.post("/api/auth/logout", json={}, headers=ORIGIN_HEADERS)
    assert logout.status_code == 200


def test_production_cookie_is_secure_http_only_and_bounded(monkeypatch):
    production_settings = replace(
        auth_saas.settings,
        auth_cookie_secure=True,
        jwt_secret="site-v1-test-signing-key-longer-than-32-bytes",
    )
    monkeypatch.setattr(auth_saas, "settings", production_settings)
    client, sessions = _client(monkeypatch)
    with sessions() as db:
        db.add(
            User(
                email="active@example.test",
                display_name="Active",
                password_hash=auth_saas.hash_password(PASSWORD),
                is_active=True,
            )
        )
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": "active@example.test", "password": PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 200
    assert "secure" in cookie
    assert "httponly" in cookie
    assert f"samesite={production_settings.auth_cookie_samesite}" in cookie
    assert f"max-age={production_settings.jwt_ttl_seconds}" in cookie


def test_rejected_account_gets_truthful_denial_without_session(monkeypatch):
    client, sessions = _client(monkeypatch)
    client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)
    with sessions() as db:
        access_request = db.scalar(select(AccessRequest))
        access_request.status = "rejected"
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": "ada@example.test", "password": PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "access_rejected"
    assert "set-cookie" not in response.headers


def test_access_approval_rejects_user_and_allows_admin(monkeypatch):
    client, sessions = _client(monkeypatch)
    client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)
    with sessions() as db:
        access_request = db.scalar(select(AccessRequest))
        request_id = access_request.id

    def reject_user(_request):
        raise HTTPException(status_code=403, detail={"status": "forbidden"})

    monkeypatch.setattr(admin_guard, "require_admin", reject_user)
    forbidden_list = client.get("/api/auth/access-requests")
    assert forbidden_list.status_code == 403
    forbidden = client.post(
        f"/api/auth/access-requests/{request_id}/approve",
        json={},
        headers=ORIGIN_HEADERS,
    )
    assert forbidden.status_code == 403
    with sessions() as db:
        assert db.get(User, db.get(AccessRequest, request_id).user_id).is_active is False

    monkeypatch.setattr(admin_guard, "require_admin", lambda _request: "admin@example.test")
    listing = client.get("/api/auth/access-requests")
    assert listing.status_code == 200
    assert listing.json()["requests"][0]["email"] == "ada@example.test"
    approved = client.post(
        f"/api/auth/access-requests/{request_id}/approve",
        json={},
        headers=ORIGIN_HEADERS,
    )
    assert approved.status_code == 200
    with sessions() as db:
        access_request = db.get(AccessRequest, request_id)
        assert access_request.status == "approved"
        assert access_request.reviewed_by == "admin@example.test"
        assert db.get(User, access_request.user_id).is_active is True


def test_access_reject_is_admin_only_and_persists_review(monkeypatch):
    client, sessions = _client(monkeypatch)
    client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)
    with sessions() as db:
        request_id = db.scalar(select(AccessRequest)).id

    def unauthenticated(_request):
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})

    monkeypatch.setattr(admin_guard, "require_admin", unauthenticated)
    denied = client.post(
        f"/api/auth/access-requests/{request_id}/reject",
        json={},
        headers=ORIGIN_HEADERS,
    )
    assert denied.status_code == 401

    monkeypatch.setattr(admin_guard, "require_admin", lambda _request: "owner@example.test")
    rejected = client.post(
        f"/api/auth/access-requests/{request_id}/reject",
        json={},
        headers=ORIGIN_HEADERS,
    )
    assert rejected.status_code == 200
    with sessions() as db:
        access_request = db.get(AccessRequest, request_id)
        assert access_request.status == "rejected"
        assert access_request.reviewed_at is not None
        assert access_request.reviewed_by == "owner@example.test"
        assert db.get(User, access_request.user_id).is_active is False


def test_competing_terminal_decisions_have_exactly_one_winner(monkeypatch):
    client, sessions = _client(monkeypatch)
    client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)
    with sessions() as db:
        request_id = db.scalar(select(AccessRequest)).id
    monkeypatch.setattr(admin_guard, "require_admin", lambda _request: "owner@example.test")
    approved = client.post(f"/api/auth/access-requests/{request_id}/approve", json={}, headers=ORIGIN_HEADERS)
    rejected = client.post(f"/api/auth/access-requests/{request_id}/reject", json={}, headers=ORIGIN_HEADERS)
    assert approved.status_code == 200
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["status"] == "already_decided"
    with sessions() as db:
        access_request = db.get(AccessRequest, request_id)
        assert access_request.status == "approved"
        assert db.get(User, access_request.user_id).is_active is True


def test_site_v1_static_contract_has_no_missing_local_assets():
    static = ROOT / "dashboard" / "static" / "site-v1"
    html = (static / "index.html").read_text(encoding="utf-8")
    js = (static / "site.js").read_text(encoding="utf-8")
    assert '/static/site-v1/site.css' in html
    assert '/static/site-v1/site.js' in html
    assert (static / "site.css").is_file()
    assert (static / "site.js").is_file()
    assert 'requestJson("/api/auth/login"' in js
    assert 'requestJson("/api/auth/register"' in js
    assert "/api/site-v1/access-requests" not in js
    assert "localStorage" not in js
    assert "innerHTML" not in js
    assert 'aria-busy") === "true"' in js
    assert "AbortController" in js
    assert "password_confirmation" in html
    assert 'async function loadWorkspace()' in js
    assert 'window.location.pathname === "/"' in js
    assert 'Заявка отправлена. После одобрения вы сможете войти.' in js


def test_security_compatibility_urls_use_canonical_admin_queue(monkeypatch):
    client, sessions = _client(monkeypatch)
    client.post("/api/auth/register", json=_registration(), headers=ORIGIN_HEADERS)
    with sessions() as db:
        request_id = db.scalar(select(AccessRequest)).id
    monkeypatch.setattr(admin_guard, "require_admin", lambda _request: "owner@example.test")
    listing = client.get("/api/security/access-requests")
    assert listing.status_code == 200
    assert listing.json()["requests"][0]["id"] == request_id
    approved = client.post(
        f"/api/security/access-requests/{request_id}/approve", json={}, headers=ORIGIN_HEADERS
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
