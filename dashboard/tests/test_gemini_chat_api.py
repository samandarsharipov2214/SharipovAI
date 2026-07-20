from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard.gemini_chat_api as gemini_api


def _app(monkeypatch) -> FastAPI:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    app = FastAPI()
    gemini_api.install_gemini_chat_api(app)
    return app


def test_gemini_key_is_required_but_never_returned(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    response = TestClient(_app(monkeypatch)).post(
        "/api/ai/chat",
        json={"message": "status", "history": []},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": {"status": "gemini_not_configured"}}
    assert "key" not in response.text.lower()


def test_cross_origin_request_is_blocked_before_chat_processing(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "server-secret-must-not-leak")
    response = TestClient(_app(monkeypatch)).post(
        "/api/ai/chat",
        headers={"Origin": "https://attacker.example"},
        json={"message": "status", "history": []},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": {"status": "cross_origin_blocked"}}
    assert "server-secret" not in response.text


def test_payload_is_strictly_typed(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "server-secret-must-not-leak")
    response = TestClient(_app(monkeypatch)).post(
        "/api/ai/chat",
        json={"message": "status", "history": [], "api_key": "injected"},
    )
    assert response.status_code == 422
    assert "injected" not in response.text


def test_successful_gateway_uses_server_key_header_and_sanitized_response(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Система работает в safe mode."}]}}
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured["request"] = kwargs
            return FakeResponse()

    monkeypatch.setenv("GEMINI_API_KEY", "server-secret-must-not-leak")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(gemini_api.httpx, "AsyncClient", FakeClient)

    response = TestClient(_app(monkeypatch)).post(
        "/api/ai/chat",
        json={
            "message": "Какой статус?",
            "history": [{"role": "assistant", "content": "Готов к проверке."}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "Система работает в safe mode."
    assert payload["model"] == "gemini-2.5-flash"
    assert payload["request_id"].startswith("gem-")
    assert response.headers["cache-control"] == "no-store"
    assert captured["request"]["headers"]["X-Goog-Api-Key"] == "server-secret-must-not-leak"
    assert "server-secret-must-not-leak" not in response.text
    assert captured["request"]["json"]["contents"][-1]["parts"][0]["text"] == "Какой статус?"
