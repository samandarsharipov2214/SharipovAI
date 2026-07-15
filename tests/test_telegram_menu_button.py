from __future__ import annotations

import dashboard.telegram_webhook_api as telegram_api


def test_restore_commands_menu_uses_native_commands_button(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_telegram(method: str, payload: dict | None = None) -> dict:
        calls.append((method, payload or {}))
        return {"ok": True, "result": True}

    monkeypatch.setattr(telegram_api, "_telegram", fake_telegram)

    result = telegram_api._restore_commands_menu()

    assert result == {"ok": True, "result": True}
    assert calls == [
        (
            "setChatMenuButton",
            {"menu_button": {"type": "commands"}},
        )
    ]


def test_set_webhook_preserves_canonical_miniapp_menu(monkeypatch):
    calls: list[tuple[str, dict]] = []

    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("WEBAPP_URL", "https://85-137-88-17.sslip.io")

    def fake_telegram(method: str, payload: dict | None = None) -> dict:
        calls.append((method, payload or {}))
        return {"ok": True, "result": True}

    monkeypatch.setattr(telegram_api, "_telegram", fake_telegram)
    monkeypatch.setattr(telegram_api, "_safe_setup_commands", lambda: {"ok": True})

    result = telegram_api._set_webhook()

    assert result["status"] == "ok"
    assert result["webapp_url"] == "https://85-137-88-17.sslip.io"
    assert calls[0] == (
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "Открыть SharipovAI",
                "web_app": {"url": "https://85-137-88-17.sslip.io"},
            }
        },
    )
    assert calls[1][0] == "setWebhook"
    assert calls[1][1]["url"] == "https://85-137-88-17.sslip.io/telegram/webhook"
