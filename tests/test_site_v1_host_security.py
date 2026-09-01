from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from dashboard.global_auth_guard import install_global_auth_guard
import dashboard.site_v1_host as site_v1_host
from dashboard.site_v1_host import install_site_v1_host

STATIC_DIR = Path(__file__).resolve().parents[1] / "dashboard" / "static"


def _protected_app(monkeypatch) -> FastAPI:
    monkeypatch.delenv("SHARIPOVAI_DISABLE_AUTH", raising=False)
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/private-probe")
    def private_probe() -> dict[str, str]:
        return {"status": "private"}

    install_site_v1_host(app)
    install_global_auth_guard(app)
    return app


def test_public_root_private_app_and_private_api_are_distinct(monkeypatch) -> None:
    with TestClient(_protected_app(monkeypatch), follow_redirects=False) as client:
        root = client.get("/")
        private_app = client.get("/app")
        private_api = client.get("/api/private-probe")

    assert root.status_code == 200
    assert root.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
    assert private_app.status_code == 303
    assert private_app.headers["location"] == "/login?next=/app"
    assert private_api.status_code == 401
    assert private_api.json()["status"] == "unauthorized"


@pytest.mark.parametrize(
    "unsafe_next",
    (
        "//evil.example",
        "https://evil.example",
        "/%2F%2Fevil.example",
        "/\\evil.example",
        "\\evil.example",
        "/ｅｖｉｌ.example",
    ),
)
def test_login_redirect_drops_every_non_app_target(unsafe_next: str) -> None:
    app = FastAPI()
    install_site_v1_host(app)

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/login", params={"next": unsafe_next})

    assert response.status_code == 303
    assert response.headers["location"] == "/?mode=login"
    assert "evil" not in response.headers["location"].lower()


def test_login_redirect_preserves_only_canonical_app_target() -> None:
    app = FastAPI()
    install_site_v1_host(app)

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/login", params={"next": "/app"})

    assert response.status_code == 303
    assert response.headers["location"] == "/?mode=login&next=/app"


def test_site_host_does_not_intercept_static_api_other_methods_or_404s() -> None:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/probe")
    def api_probe() -> dict[str, str]:
        return {"owner": "api"}

    @app.post("/app")
    def app_post_probe() -> dict[str, str]:
        return {"owner": "post-route"}

    install_site_v1_host(app)

    with TestClient(app, follow_redirects=False) as client:
        static_asset = client.get("/static/site-v1/site.css")
        api = client.get("/api/probe")
        app_post = client.post("/app")
        missing = client.get("/not-a-site-route")

    assert static_asset.status_code == 200
    assert static_asset.headers["content-type"].startswith("text/css")
    assert api.json() == {"owner": "api"}
    assert app_post.json() == {"owner": "post-route"}
    assert missing.status_code == 404


def test_missing_site_index_fails_closed_instead_of_rendering_legacy_root(monkeypatch, tmp_path) -> None:
    app = FastAPI()

    @app.get("/")
    def legacy_root() -> str:
        return "legacy operational dashboard"

    monkeypatch.setattr(site_v1_host, "SITE_INDEX", tmp_path / "missing-index.html")
    install_site_v1_host(app)
    install_global_auth_guard(app)

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 503
    assert "legacy operational dashboard" not in response.text
