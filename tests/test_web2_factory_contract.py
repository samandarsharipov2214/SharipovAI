from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app


def test_create_app_serves_web2_on_legacy_ui_routes() -> None:
    client = TestClient(create_app())
    for path in ("/", "/market", "/news", "/settings", "/stress-lab"):
        response = client.get(path)
        assert response.status_code == 200
        assert "SharipovAI — торговая система" in response.text
        assert "/static/web2/" in response.text


def test_demo_api_does_not_override_canonical_login_page() -> None:
    response = TestClient(create_app()).get("/login")
    assert response.status_code == 200
    assert "Запросить доступ" in response.text
    assert "minlength" in response.text
