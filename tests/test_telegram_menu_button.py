from __future__ import annotations

import dashboard.telegram_webhook_api as telegram_api


def test_safe_set_menu_button_uses_configured_webapp_url(monkeypatch):
    calls: list[tuple[str, dict]] = []

    monkeypatch.setenv("WEBAPP_URL", "https://85-137-88-17.sslip.io/")

    def fake_telegram(method: str, payload: dict | None = None) -> dict:
        calls.append((method, payload or {}))
        return {"ok": True, "result": True}

    monkeypatch.setattr(telegram_api, "_telegram", fake_telegram)

    result = telegram_api._safe_set_menu_button()

    assert result == {"ok": True, "result": True}
    assert calls == [
        (
            "setChatMenuButton",
            {
                "menu_button": {
                    "type": "web_app",
                    "text": "Открыть SharipovAI",
                    "web_app": {"url": "https://85-137-88-17.sslip.io"},
                }
            },
        )
    ]


def test_safe_set_menu_button_fails_closed_without_webapp_url(monkeypatch):
    monkeypatch.delenv("WEBAPP_URL", raising=False)

    called = False

    def fake_telegram(method: str, payload: dict | None = None) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(telegram_api, "_telegram", fake_telegram)

    assert telegram_api._safe_set_menu_button() == {
        "ok": False,
        "error": "WEBAPP_URL_missing",
    }
    assert called is False
