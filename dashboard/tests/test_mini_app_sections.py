"""Tests for the current Telegram Mini App / Web2 shell contracts."""
from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_mini_app_uses_current_web2_navigation() -> None:
    response = _client().get("/?lang=ru")
    assert response.status_code == 200
    text = response.text
    for page_id in (
        "overview", "market", "decision", "portfolio", "trades", "bots",
        "chat", "news", "risk", "bybit", "learning", "control",
        "evidence", "virtual", "reports", "settings",
    ):
        assert f'data-page="{page_id}"' in text
    for label in ("Обзор", "Рынок", "Решение ИИ", "Портфель", "Сделки", "Новости", "Настройки"):
        assert label in text


def test_mini_app_exposes_safe_exchange_shell() -> None:
    response = _client().get("/?lang=ru")
    assert response.status_code == 200
    text = response.text
    assert 'data-page="bybit"' in text
    assert ">Bybit<" in text
    assert "Безопасное исполнение" in text
    assert "/static/web2/exchange_execution_settings_v18.js" in text
    assert "Math.random" not in text


def test_mini_app_exchange_renderer_is_display_only() -> None:
    response = _client().get("/static/mini-app-live.js")
    assert response.status_code == 200
    text = response.text
    assert "renderExchangeMonitor" in text
    assert "exchange_status" in text
    assert "online_monitoring" in text
    assert "/api/demo/state" not in text
    assert "/api/demo/chat" not in text
    assert "Math.random" not in text
    assert "fetch(" not in text


def test_canonical_virtual_account_and_ai_routes_exist() -> None:
    client = _client()
    assert client.get("/api/virtual-account/state").status_code == 200
    assert client.get("/api/ai-bots").status_code == 200
    stress = client.post("/api/stress-lab/run", json={"price_drop_percent": 10})
    assert stress.status_code == 200
