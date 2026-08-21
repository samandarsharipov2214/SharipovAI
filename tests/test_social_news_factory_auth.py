from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.auth_guard_middleware import AuthGuardMiddleware


def _app(monkeypatch, *, username: str | None = None) -> FastAPI:
    import dashboard.auth_guard_middleware as auth

    monkeypatch.setattr(auth, "session_username", lambda request: username)
    app = FastAPI()
    app.add_middleware(AuthGuardMiddleware)

    @app.get("/api/social-news")
    def social_news():
        return {"status": "ok"}

    @app.get("/api/social-news/rss/status")
    def social_news_rss_status():
        return {"status": "ok"}

    @app.post("/api/social-news/rss/refresh")
    def social_news_rss_refresh():
        return {"status": "mutated"}

    @app.post("/api/social-news/telegram/refresh")
    def social_news_telegram_refresh():
        return {"status": "mutated"}

    @app.post("/api/social-news/analyze")
    def social_news_analyze():
        return {"status": "mutated"}

    return app


def _canonical_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthGuardMiddleware)

    @app.post("/api/social-news/rss/refresh")
    def social_news_rss_refresh():
        return {"status": "mutated"}

    return app


def test_social_news_mutations_require_factory_session(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)

    with TestClient(_app(monkeypatch)) as client:
        assert client.get("/api/social-news").status_code == 200
        assert client.get("/api/social-news/rss/status").status_code == 200
        assert client.post("/api/social-news/rss/refresh").status_code == 401
        assert client.post("/api/social-news/telegram/refresh").status_code == 401
        assert client.post("/api/social-news/analyze").status_code == 401

    with TestClient(_app(monkeypatch, username="verified-user")) as client:
        assert client.post("/api/social-news/rss/refresh").status_code == 200
        assert client.post("/api/social-news/telegram/refresh").status_code == 200
        assert client.post("/api/social-news/analyze").status_code == 200


def test_social_news_mutation_accepts_canonical_saas_principal(monkeypatch) -> None:
    import dashboard.auth_saas as auth_saas

    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    monkeypatch.setattr(
        auth_saas,
        "resolve_authenticated_principal",
        lambda request: "saas-admin@example.test",
    )

    with TestClient(_canonical_app()) as client:
        assert client.post("/api/social-news/rss/refresh").status_code == 200
