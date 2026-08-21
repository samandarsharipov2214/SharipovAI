from __future__ import annotations

import telegram_bot
from telegram_presentation import format_news_item


def test_missing_news_evidence_is_explicit_instead_of_fabricated_defaults() -> None:
    rendered = format_news_item({}, index=1)

    assert "Заголовок не передан источником" in rendered
    assert "Источник не указан" in rendered
    assert "достоверность не указана" in rendered
    assert "статус подтверждения не указан" in rendered
    assert "AI: <b>не указано</b>" in rendered
    assert "ссылка не передана источником" in rendered
    assert "0%</b>" not in rendered
    assert "AI: <b>WATCH</b>" not in rendered
    assert "подтверждение не требуется" not in rendered


def test_provided_news_evidence_is_preserved() -> None:
    rendered = format_news_item(
        {
            "title": "Market update",
            "source_name": "Example Wire",
            "credibility_percent": 87,
            "published_at": "2026-08-20T12:00:00Z",
            "url": "https://example.com/news?id=1&lang=ru",
            "needs_confirmation": True,
            "ai_action": "WAIT",
        },
        index=2,
    )

    assert "Market update" in rendered
    assert "Example Wire" in rendered
    assert "достоверность <b>87%</b>" in rendered
    assert "нужно подтверждение" in rendered
    assert "AI: <b>WAIT</b>" in rendered
    assert 'href="https://example.com/news?id=1&amp;lang=ru"' in rendered


def test_supported_legacy_news_aliases_are_preserved() -> None:
    rendered = format_news_item(
        {
            "headline": "Legacy headline",
            "source": "Legacy Wire",
            "credibility": 73,
        },
        index=3,
    )

    assert "Legacy headline" in rendered
    assert "Legacy Wire" in rendered
    assert "достоверность <b>73%</b>" in rendered
    assert "Заголовок не передан источником" not in rendered
    assert "Источник не указан" not in rendered


def test_invalid_credibility_does_not_render_as_a_real_percentage() -> None:
    for credibility in ("unknown", False, True):
        rendered = format_news_item(
            {
                "title": "Market update",
                "source_name": "Example Wire",
                "credibility_percent": credibility,
            },
            index=4,
        )

        assert "достоверность не указана" in rendered
        assert f"{credibility}%" not in rendered
        assert "достоверность <b>0%</b>" not in rendered
        assert "достоверность <b>1%</b>" not in rendered


def test_source_trust_is_not_presented_as_item_credibility() -> None:
    rendered = format_news_item(
        {
            "title": "Market update",
            "source_name": "Example Wire",
            "trust_score": 95,
        },
        index=5,
    )

    assert "достоверность не указана" in rendered
    assert "достоверность <b>95%</b>" not in rendered


def test_live_telegram_news_path_uses_truthful_formatter(monkeypatch) -> None:
    payload = {
        "summary": {},
        "items": [
            {
                "title": "",
                "source_name": "",
                "credibility_percent": False,
                "published_at": "",
                "url": "",
            }
        ],
    }
    monkeypatch.setattr("news_monitor.analyzer.analyzed_news_payload", lambda: payload)

    rendered = telegram_bot.news_text()

    assert "Заголовок не передан источником" in rendered
    assert "Источник не указан" in rendered
    assert "достоверность не указана" in rendered
    assert "статус подтверждения не указан" in rendered
    assert "AI: <b>не указано</b>" in rendered
    assert "ссылка не передана источником" in rendered
    assert "Средняя достоверность: <b>не указана</b>" in rendered
    assert "Нужно подтверждение: <b>не указано</b>" in rendered
    assert "Новость</b>" not in rendered
    assert "unknown" not in rendered
    assert "доверие 0%" not in rendered


def test_live_telegram_news_path_preserves_numeric_confirmation_count(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_monitor.analyzer.analyzed_news_payload",
        lambda: {"summary": {"needs_confirmation": 3}, "items": []},
    )

    rendered = telegram_bot.news_text()

    assert "Нужно подтверждение: <b>3</b>" in rendered
    assert "Нужно подтверждение: <b>не указано</b>" not in rendered


def test_live_telegram_news_path_reports_malformed_items(monkeypatch) -> None:
    payload = {
        "summary": {},
        "items": ["broken", {"title": "Valid item", "source_name": "Wire"}, 42],
    }
    monkeypatch.setattr("news_monitor.analyzer.analyzed_news_payload", lambda: payload)

    rendered = telegram_bot.news_text()

    assert "Некорректных записей новостей: 2" in rendered
    assert "Valid item" in rendered
    assert "Заголовок не передан источником" not in rendered


def test_live_telegram_news_path_reports_non_list_items(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_monitor.analyzer.analyzed_news_payload",
        lambda: {"summary": {}, "items": "not-a-list"},
    )

    rendered = telegram_bot.news_text()

    assert "поле items должно быть списком" in rendered
    assert "Заголовок не передан источником" not in rendered


def test_live_telegram_news_path_stays_below_html_clip_limit(monkeypatch) -> None:
    payload = {
        "summary": {"average_credibility_percent": 80, "needs_confirmation": False},
        "items": [
            {
                "title": "&" * 5000,
                "source_name": "Wire",
                "credibility_percent": 80,
                "published_at": "2026-08-20T12:00:00Z",
                "url": "https://example.com/" + "x" * 5000,
                "needs_confirmation": False,
                "ai_action": "WAIT",
            }
        ],
    }
    monkeypatch.setattr("news_monitor.analyzer.analyzed_news_payload", lambda: payload)

    rendered = telegram_bot.news_text()

    assert len(rendered) <= 3800
    assert telegram_bot._clip(rendered) == rendered
    assert rendered.count("<b>") == rendered.count("</b>")
    assert rendered.count("<a href=") == rendered.count("</a>")
    assert "ответ достиг безопасного лимита Telegram" in rendered


def test_live_telegram_news_path_reserves_room_for_overflow_notice(monkeypatch) -> None:
    payload = {
        "summary": {"average_credibility_percent": 80, "needs_confirmation": 2},
        "items": [
            {
                "title": "A" * 3000,
                "source_name": "Wire",
                "credibility_percent": 80,
                "published_at": "2026-08-20T12:00:00Z",
            },
            {
                "title": "B" * 5000,
                "source_name": "Wire",
                "credibility_percent": 80,
                "published_at": "2026-08-20T12:00:00Z",
            },
        ],
    }
    monkeypatch.setattr("news_monitor.analyzer.analyzed_news_payload", lambda: payload)

    rendered = telegram_bot.news_text()

    assert len(rendered) <= 3800
    assert "Один внутренний модуль упал" not in rendered
    assert "Нужно подтверждение: <b>2</b>" in rendered
    assert "ответ достиг безопасного лимита Telegram" in rendered
    assert rendered.count("<b>") == rendered.count("</b>")
