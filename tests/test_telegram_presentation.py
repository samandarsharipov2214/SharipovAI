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


def test_news_text_lists_verified_summary_and_sources() -> None:
    text = news_text()

    assert "Новости: источники и время" in text
    assert "Проверено:" in text
    assert "Средняя достоверность" in text
    assert "Нужно подтверждение" in text
    assert "Правило: один источник не даёт разрешение на сделку" in text
    assert "Источник:" in text or "Новостей пока нет" in text


def test_now_text_exposes_current_decision_regime_risk_and_next_step() -> None:
    text = now_text()

    assert "Текущее решение SharipovAI" in text
    assert "Время проверки:" in text
    assert "Решение:" in text
    assert "Действие:" in text
    assert "Режим рынка:" in text
    assert "Риск:" in text
    assert "Следующий шаг: /news или /why" in text


def test_market_regime_helpers_explain_mixed() -> None:
    assert market_regime_ru("mixed") == "смешанный рынок (mixed)"
    assert "Сигналы противоречат" in market_regime_explanation("mixed")


def test_main_keyboard_exposes_current_navigation_without_raw_order_actions() -> None:
    keyboard = main_keyboard()
    rows = keyboard["inline_keyboard"]
    buttons = [button for row in rows for button in row]
    callbacks = {button.get("callback_data") for button in buttons if button.get("callback_data")}
    labels = {button.get("text") for button in buttons}

    assert callbacks & {"now", "overview"}
    assert any(label and ("Сейчас" in label or "Обзор" in label) for label in labels)
    assert "buy" not in callbacks
    assert "sell" not in callbacks
    assert "place_order" not in callbacks
