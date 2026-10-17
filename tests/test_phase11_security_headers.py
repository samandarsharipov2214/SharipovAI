from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from dashboard.security_headers import install_security_headers


def _app() -> FastAPI:
    app = FastAPI()
    install_security_headers(app)

    @app.get("/api/probe")
    def api_probe():
        return {"status": "ok"}

    @app.get("/")
    def html_probe():
        return HTMLResponse("<h1>ok</h1>")

    @app.get("/app")
    def cabinet_html():
        return HTMLResponse("<h1>cabinet shell</h1>")

    @app.get("/security")
    def protected_html():
        return HTMLResponse("<h1>security</h1>")

    return app


def test_api_and_html_receive_non_cacheable_security_headers():
    client = TestClient(_app())
    for path in ("/api/probe", "/"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "same-origin"
        assert "camera=()" in response.headers["permissions-policy"]
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
        assert "no-store" in response.headers["cache-control"]


def test_hsts_is_sent_only_for_https_or_trusted_proxy_scheme(monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_HSTS_ENABLED", "1")
    client = TestClient(_app())
    plain = client.get("/api/probe")
    assert "strict-transport-security" not in plain.headers
    proxied = client.get(
        "/api/probe",
        headers={"x-forwarded-proto": "https"},
    )
    assert proxied.headers["strict-transport-security"].startswith("max-age=31536000")


def test_hsts_can_be_disabled_for_non_tls_development(monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_HSTS_ENABLED", "0")
    response = TestClient(_app()).get(
        "/api/probe",
        headers={"x-forwarded-proto": "https"},
    )
    assert "strict-transport-security" not in response.headers


def test_chatgpt_embed_is_opt_in_and_only_for_site_v1_html(monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_CHATGPT_EMBED_ENABLED", "1")
    client = TestClient(_app())
    for path in ("/", "/app"):
        response = client.get(path)
        assert response.status_code == 200
        assert "x-frame-options" not in response.headers
        csp = response.headers["content-security-policy"]
        assert csp == "frame-ancestors 'self' https://chatgpt.com https://chat.openai.com"
        assert "https://evil.example" not in csp
        assert response.headers["cache-control"].startswith("no-store")
    for path in ("/security", "/api/probe", "/not-found"):
        response = client.get(path)
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors https://chatgpt.com" not in response.headers.get("content-security-policy", "")


def test_chatgpt_embed_switch_default_and_explicit_disable(monkeypatch):
    monkeypatch.delenv("SHARIPOVAI_CHATGPT_EMBED_ENABLED", raising=False)
    assert TestClient(_app()).get("/").headers["x-frame-options"] == "DENY"
    monkeypatch.setenv("SHARIPOVAI_CHATGPT_EMBED_ENABLED", "0")
    assert TestClient(_app()).get("/app").headers["x-frame-options"] == "DENY"


def test_vps_caddy_does_not_override_app_frame_policy():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    caddy = (root / "deploy/vps/Caddyfile").read_text(encoding="utf-8")
    compose = (root / "deploy/vps/docker-compose.yml").read_text(encoding="utf-8")
    assert 'X-Frame-Options "SAMEORIGIN"' not in caddy
    assert "SHARIPOVAI_CHATGPT_EMBED_ENABLED" in compose
