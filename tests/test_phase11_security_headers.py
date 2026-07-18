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
