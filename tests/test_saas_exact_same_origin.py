from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from dashboard.auth_saas import ensure_same_origin


def _client(base_url: str) -> TestClient:
    app = FastAPI()

    @app.post("/probe")
    def probe(request: Request) -> dict[str, str]:
        ensure_same_origin(request)
        return {"status": "ok"}

    return TestClient(app, base_url=base_url)


def test_same_host_but_different_scheme_is_cross_origin() -> None:
    client = _client("https://example.test")

    blocked = client.post("/probe", headers={"Origin": "http://example.test"})

    assert blocked.status_code == 403
    assert blocked.json()["detail"]["status"] == "cross_origin_blocked"


def test_exact_https_origin_is_allowed() -> None:
    client = _client("https://example.test")

    response = client.post("/probe", headers={"Origin": "https://example.test"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_exact_http_origin_is_allowed_for_http_request() -> None:
    client = _client("http://example.test")

    response = client.post("/probe", headers={"Origin": "http://example.test"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
