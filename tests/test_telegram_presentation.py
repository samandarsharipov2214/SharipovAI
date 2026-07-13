from __future__ import annotations

from telegram_bot import main_keyboard, news_text, now_text
from telegram_presentation import format_news_item, market_regime_explanation, market_regime_ru, news_title_ru


def test_news_title_is_localized_for_known_demo_titles() -> None:
    assert news_title_ru("Breaking: Large BTC liquidation alert reported on social media") == "Срочный сигнал: в соцсетях сообщили о крупной ликвидации по BTC"


def test_format_news_item_contains_source_link_and_time() -> None:
    item = {
        "title": "Bitcoin ETF inflow increases as market volatility cools",
        "source_name": "Cointelegraph",
        "credibility_percent": 99,
        "published_at": "2026-07-09T02:00:00+00:00",
        "url": "https://cointelegraph.com/rss",
        "needs_confirmation": False,
        "ai_action": "WATCH",
    }
    text = format_news_item(item, index=1)
    assert "Приток в Bitcoin ETF" in text
    assert "Источник:" in text
    assert "Cointelegraph" in text
    assert "Время:" in text
    assert "Открыть источник" in text
    assert "https://cointelegraph.com/rss" in text


def test_news_text_is_transparent_when_live_feed_is_empty_or_unavailable() -> None:
    text = news_text()
    assert "Новости" in text
    assert ("Средняя достоверность" in text) or ("внутренний модуль упал" in text)
    assert ("один источник" in text.lower()) or ("Попробуй" in text)


def test_now_text_reports_decision_or_explicit_module_failure() -> None:
    text = now_text()
    assert ("Текущее решение SharipovAI" in text) or ("Текущее решение" in text)
    assert ("Решение:" in text) or ("внутренний модуль упал" in text)


def test_market_regime_helpers_explain_mixed() -> None:
    assert market_regime_ru("mixed") == "смешанный рынок (mixed)"
    assert "Сигналы противоречат" in market_regime_explanation("mixed")


def test_main_keyboard_has_current_decision_action() -> None:
    keyboard = main_keyboard()
    texts = [button["text"] for row in keyboard["inline_keyboard"] for button in row]
    assert any("решение" in text.lower() or "обзор" in text.lower() for text in texts)
    assert any(button.get("callback_data") == "overview" for row in keyboard["inline_keyboard"] for button in row)
