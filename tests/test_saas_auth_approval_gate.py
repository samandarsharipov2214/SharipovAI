from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import dashboard.auth_saas as auth_saas
from dashboard.models_saas import AccessRequest, Base, User


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def _app_with_saas_auth(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(auth_saas, "SessionLocal", session_factory)
    app = FastAPI()
    auth_saas.install_saas_auth_api(app)
    return app, session_factory


def test_registration_is_pending_and_does_not_issue_session(monkeypatch):
    app, session_factory = _app_with_saas_auth(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/auth/register",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={
            "email": "pending@example.com",
            "password": "correct-horse-battery-staple",
            "password_confirmation": "correct-horse-battery-staple",
            "name": "Pending User",
            "contact": "@pending",
            "reason": "Research",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    assert response.json()["authenticated"] is False
    assert auth_saas.settings.auth_cookie_name not in response.cookies
    assert "set-cookie" not in response.headers

    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == "pending@example.com"))
        assert user is not None
        assert user.is_active is False
        assert user.subscription is None
        access_request = db.scalar(select(AccessRequest).where(AccessRequest.user_id == user.id))
        assert access_request is not None
        assert access_request.status == "pending"
        assert access_request.contact == "@pending"

    login = client.post(
        "/api/auth/login",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={
            "email": "pending@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    assert login.status_code == 403
    assert login.json()["detail"]["status"] == "pending_approval"


def test_jwt_principal_is_revalidated_against_active_user(monkeypatch):
    app, session_factory = _app_with_saas_auth(monkeypatch)
    client = TestClient(app)

    with session_factory() as db:
        user = User(
            email="revoked@example.com",
            display_name="Revoked",
            password_hash="not-used",
            is_active=False,
        )
        db.add(user)
        db.commit()
        token = auth_saas.issue_access_token(user)

    client.cookies.set(auth_saas.settings.auth_cookie_name, token)
    revoked = client.get("/api/auth/me")
    assert revoked.status_code == 200
    assert revoked.json() == {
        "status": "anonymous",
        "authenticated": False,
        "user": None,
    }

    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == "revoked@example.com"))
        assert user is not None
        user.is_active = True
        db.commit()

    active = client.get("/api/auth/me")
    assert active.status_code == 200
    assert active.json()["authenticated"] is True
    assert active.json()["user"]["email"] == "revoked@example.com"

    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == "revoked@example.com"))
        assert user is not None
        db.delete(user)
        db.commit()

    deleted = client.get("/api/auth/me")
    assert deleted.status_code == 200
    assert deleted.json() == {
        "status": "anonymous",
        "authenticated": False,
        "user": None,
    }
