from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.auth_guard_middleware import AuthGuardMiddleware


def _app(monkeypatch, *, username: str | None = None) -> FastAPI:
    import dashboard.auth_guard_middleware as auth

    monkeypatch.setattr(auth, "session_username", lambda request: username)
    app = FastAPI()
    app.add_middleware(AuthGuardMiddleware)

    @app.get("/")
    def private_page():
        return {"status": "private"}

    @app.get("/api/private")
    def private_api():
        return {"status": "private"}

    @app.post("/telegram/webhook")
    def telegram_webhook():
        return {"ok": True}

    @app.post("/api/telegram/miniapp-auth")
    def miniapp_auth():
        return {"ok": True}

    @app.get("/api/check-ai")
    def public_check():
        return {"status": "ok"}

    return app


def test_factory_auth_requires_explicit_false_disable_flag(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    with TestClient(_app(monkeypatch)) as client:
        html = client.get("/private-page", follow_redirects=False)
        api = client.get("/api/private")

    assert html.status_code == 303
    assert html.headers["location"] == "/login?next=/private-page"
    assert api.status_code == 401
    assert api.json()["status"] == "unauthorized"


def test_factory_app_is_usable_when_flag_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    with TestClient(_app(monkeypatch)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/private").status_code == 200


def test_authenticated_session_can_access_private_routes(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    with TestClient(_app(monkeypatch, username="samandar")) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/private").status_code == 200


def test_self_authenticated_telegram_routes_remain_public(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    with TestClient(_app(monkeypatch)) as client:
        assert client.post("/telegram/webhook").status_code == 200
        assert client.post("/api/telegram/miniapp-auth").status_code == 200
        assert client.get("/api/check-ai").status_code == 200


def test_auth_bypass_requires_explicit_truthy_value(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    with TestClient(_app(monkeypatch)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/private").status_code == 200

    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    with TestClient(_app(monkeypatch)) as client:
        assert client.get("/api/private").status_code == 401
