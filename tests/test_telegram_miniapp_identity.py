from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import dashboard.auth_saas as auth_saas
import dashboard.telegram_webhook_api as telegram_api
from dashboard.models_saas import Base, User
from dashboard.telegram_identity import bind_telegram_identity, get_telegram_identity_binding
from storage.project_database import ProjectDatabase


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


def _app(monkeypatch, tmp_path):
    session_factory = _session_factory()
    monkeypatch.setattr(telegram_api, "SessionLocal", session_factory)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'project.db'}")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "0")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setattr(
        telegram_api,
        "validate_miniapp_init_data",
        lambda _value: {
            "ok": True,
            "auth_date": 1_700_000_000,
            "user": {"id": 424242, "username": "linked-user"},
            "query_id": "q1",
        },
    )
    app = FastAPI()
    telegram_api.install_telegram_webhook_api(app)
    return app, session_factory


def _add_user(session_factory, *, email: str, active: bool) -> User:
    with session_factory() as db:
        user = User(
            email=email,
            display_name=email.split("@", 1)[0],
            password_hash="not-used",
            is_active=active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def test_unlinked_telegram_identity_cannot_authenticate_without_canonical_session(monkeypatch, tmp_path):
    app, _ = _app(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/telegram/miniapp-auth",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"init_data": "signed-init-data"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "telegram_identity_not_linked"
    assert auth_saas.settings.auth_cookie_name not in response.cookies
    assert "set-cookie" not in response.headers


def test_approved_canonical_session_links_telegram_and_future_init_data_recreates_session(monkeypatch, tmp_path):
    app, session_factory = _app(monkeypatch, tmp_path)
    user = _add_user(session_factory, email="approved@example.com", active=True)
    client = TestClient(app)
    client.cookies.set(auth_saas.settings.auth_cookie_name, auth_saas.issue_access_token(user))

    linked = client.post(
        "/api/telegram/miniapp-auth",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"init_data": "signed-init-data"},
    )

    assert linked.status_code == 200
    assert linked.json()["authenticated"] is True
    assert linked.json()["user"]["email"] == "approved@example.com"
    assert auth_saas.settings.auth_cookie_name in linked.cookies
    binding = get_telegram_identity_binding(424242, database=ProjectDatabase())
    assert binding is not None
    assert binding.canonical_user_id == user.id

    fresh_client = TestClient(app)
    restored = fresh_client.post(
        "/api/telegram/miniapp-auth",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"init_data": "signed-init-data"},
    )
    assert restored.status_code == 200
    assert restored.json()["authenticated"] is True
    assert restored.json()["user"]["id"] == user.id
    assert auth_saas.settings.auth_cookie_name in restored.cookies


def test_bound_inactive_or_deleted_canonical_user_is_denied(monkeypatch, tmp_path):
    app, session_factory = _app(monkeypatch, tmp_path)
    inactive = _add_user(session_factory, email="inactive@example.com", active=False)
    bind_telegram_identity(424242, inactive.id, database=ProjectDatabase())
    client = TestClient(app)

    inactive_response = client.post(
        "/api/telegram/miniapp-auth",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"init_data": "signed-init-data"},
    )
    assert inactive_response.status_code == 403
    assert inactive_response.json()["detail"] == "telegram_identity_not_approved"
    assert "set-cookie" not in inactive_response.headers

    with session_factory() as db:
        stored = db.get(User, inactive.id)
        assert stored is not None
        db.delete(stored)
        db.commit()

    deleted_response = client.post(
        "/api/telegram/miniapp-auth",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"init_data": "signed-init-data"},
    )
    assert deleted_response.status_code == 403
    assert deleted_response.json()["detail"] == "telegram_identity_not_approved"
    assert "set-cookie" not in deleted_response.headers


def test_existing_telegram_binding_cannot_be_reassigned_by_another_session(monkeypatch, tmp_path):
    app, session_factory = _app(monkeypatch, tmp_path)
    first = _add_user(session_factory, email="first@example.com", active=True)
    second = _add_user(session_factory, email="second@example.com", active=True)
    bind_telegram_identity(424242, first.id, database=ProjectDatabase())

    client = TestClient(app)
    client.cookies.set(auth_saas.settings.auth_cookie_name, auth_saas.issue_access_token(second))
    response = client.post(
        "/api/telegram/miniapp-auth",
        headers={"host": "testserver", "origin": "http://testserver"},
        json={"init_data": "signed-init-data"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "telegram_identity_conflict"
    binding = get_telegram_identity_binding(424242, database=ProjectDatabase())
    assert binding is not None
    assert binding.canonical_user_id == first.id
