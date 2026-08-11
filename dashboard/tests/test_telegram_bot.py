"""Tests for the SharipovAI Telegram worker."""

from __future__ import annotations

import telegram_bot


def test_main_keyboard_without_webapp_url(monkeypatch) -> None:
    """Keyboard works without Mini App URL."""

    monkeypatch.delenv("WEBAPP_URL", raising=False)

    keyboard = telegram_bot.main_keyboard()

    assert "inline_keyboard" in keyboard
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "overview"
    assert keyboard["inline_keyboard"][0][1]["callback_data"] == "portfolio"
    assert keyboard["inline_keyboard"][1][0]["callback_data"] == "risk"
    assert keyboard["inline_keyboard"][1][1]["callback_data"] == "ai_chat"


def test_main_keyboard_with_webapp_url(monkeypatch) -> None:
    """Keyboard includes Telegram Mini App button when WEBAPP_URL is set."""

    monkeypatch.setenv("WEBAPP_URL", "https://example.com")

    keyboard = telegram_bot.main_keyboard()

    assert keyboard["inline_keyboard"][0][0]["web_app"] == {"url": "https://example.com"}
    assert keyboard["inline_keyboard"][1][0]["callback_data"] == "overview"


def test_bot_token_missing_raises_at_runtime(monkeypatch) -> None:
    """Missing BOT_TOKEN raises only when the token is actually requested."""

    monkeypatch.delenv("BOT_TOKEN", raising=False)

    try:
        telegram_bot.bot_token()
    except RuntimeError as exc:
        assert "BOT_TOKEN is not set" in str(exc)
    else:
        raise AssertionError("bot_token() should raise when BOT_TOKEN is missing")


def test_legacy_handler_never_serves_demo_state(monkeypatch) -> None:
    """The compatibility package cannot become a second Telegram truth source."""

    sent: list[tuple[int, str, dict[str, object] | None]] = []

    def fake_send_message(chat_id: int, text: str, keyboard: dict[str, object] | None = None) -> None:
        sent.append((chat_id, text, keyboard))

    monkeypatch.setattr(telegram_bot, "send_message", fake_send_message)
    telegram_bot.handle_message({"chat": {"id": 123}, "text": "/start"})

    assert sent
    assert sent[0][0] == 123
    assert "compatibility-вход отключён" in sent[0][1]
    assert "demo-баланс" in sent[0][1]
    assert sent[0][2] is not None


def test_bot_ai_reply_does_not_fabricate_portfolio_or_risk() -> None:
    """Legacy direct replies must not invent balances or risk status."""

    reply = telegram_bot.bot_ai_reply("покажи портфель и баланс")

    assert "10,000.00 USDT" not in reply
    assert "compatibility-вход отключён" in reply


def test_handle_plain_message_is_explicitly_retired(monkeypatch) -> None:
    """The retired handler cannot call the historical direct reply path."""

    sent: list[tuple[int, str, dict[str, object] | None]] = []

    def fake_send_message(chat_id: int, text: str, keyboard: dict[str, object] | None = None) -> None:
        sent.append((chat_id, text, keyboard))

    monkeypatch.setattr(telegram_bot, "send_message", fake_send_message)

    telegram_bot.handle_message({"chat": {"id": 123}, "text": "что с риском?"})

    assert sent
    assert sent[0][0] == 123
    assert "compatibility-вход отключён" in sent[0][1]
    assert sent[0][2] is not None


def test_legacy_polling_is_rejected_even_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "1")

    try:
        telegram_bot.poll()
    except RuntimeError as exc:
        assert "legacy Telegram polling is retired" in str(exc)
    else:
        raise AssertionError("legacy poller must not start")
