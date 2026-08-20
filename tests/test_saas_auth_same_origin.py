from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.auth_saas import ensure_same_origin


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/check-origin")
    def check_origin(request):
        ensure_same_origin(request)
        return {"status": "ok"}

    return app


def test_same_origin_accepts_exact_http_and_https_authority() -> None:
    with TestClient(_app(), base_url="https://sharipovai.example") as client:
        response = client.post("/check-origin", headers={"Origin": "https://sharipovai.example"})
    assert response.status_code == 200

    with TestClient(_app(), base_url="http://sharipovai.example") as client:
        response = client.post("/check-origin", headers={"Origin": "http://sharipovai.example"})
    assert response.status_code == 200


def test_same_origin_rejects_prefix_domain_bypass() -> None:
    with TestClient(_app(), base_url="https://sharipovai.example") as client:
        response = client.post(
            "/check-origin",
            headers={"Origin": "https://sharipovai.example.evil.test"},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "cross_origin_blocked"


def test_same_origin_rejects_port_mismatch() -> None:
    with TestClient(_app(), base_url="https://sharipovai.example") as client:
        response = client.post(
            "/check-origin",
            headers={"Origin": "https://sharipovai.example:444"},
        )
    assert response.status_code == 403


def test_same_origin_rejects_origin_with_path_query_or_userinfo() -> None:
    invalid_origins = (
        "https://sharipovai.example/extra",
        "https://sharipovai.example?next=/",
        "https://user@sharipovai.example",
    )
    with TestClient(_app(), base_url="https://sharipovai.example") as client:
        for origin in invalid_origins:
            response = client.post("/check-origin", headers={"Origin": origin})
            assert response.status_code == 403, origin
