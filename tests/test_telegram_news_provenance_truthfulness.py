from __future__ import annotations

from news_monitor.analyzer import analyze_items
from telegram_presentation import format_news_item


def test_analyzer_preserves_timestamp_quality_evidence() -> None:
    item = analyze_items(
        [
            {
                "source_id": "manual",
                "source_name": "Wire",
                "title": "BTC update",
                "url": "https://example.com/news",
                "published_at": "2026-08-21T04:00:00+00:00",
                "timestamp_quality": "fetch_fallback_missing_or_invalid",
            }
        ]
    )[0].to_dict()

    assert item["timestamp_quality"] == "fetch_fallback_missing_or_invalid"


def test_fallback_timestamp_is_not_presented_as_fresh_publication_time() -> None:
    rendered = format_news_item(
        {
            "title": "BTC update",
            "source_name": "Wire",
            "published_at": "2026-08-21T04:00:00+00:00",
            "timestamp_quality": "fetch_fallback_missing_or_invalid",
        },
        index=1,
    )

    assert "время публикации не подтверждено источником" in rendered
    assert "только что" not in rendered


def test_missing_timestamp_quality_is_treated_as_unverified() -> None:
    rendered = format_news_item(
        {
            "title": "Legacy saved item",
            "source_name": "Wire",
            "published_at": "2026-08-21T04:00:00+00:00",
        },
        index=1,
    )

    assert "время публикации не подтверждено источником" in rendered
    assert "только что" not in rendered


def test_unsafe_saved_news_url_is_not_emitted_as_telegram_link() -> None:
    rendered = format_news_item(
        {
            "title": "Saved item",
            "source_name": "Wire",
            "url": "javascript:alert(1)",
        },
        index=1,
    )

    assert "адрес источника небезопасен или некорректен" in rendered
    assert "<a href=" not in rendered
    assert "javascript:" not in rendered


def test_relative_saved_news_url_is_not_emitted_as_telegram_link() -> None:
    rendered = format_news_item(
        {
            "title": "Saved item",
            "source_name": "Wire",
            "url": "/news/123",
        },
        index=1,
    )

    assert "адрес источника небезопасен или некорректен" in rendered
    assert "<a href=" not in rendered


def test_safe_public_news_url_is_preserved() -> None:
    rendered = format_news_item(
        {
            "title": "Saved item",
            "source_name": "Wire",
            "url": "https://example.com/news?id=1&lang=ru",
        },
        index=1,
    )

    assert 'href="https://example.com/news?id=1&amp;lang=ru"' in rendered
    assert "небезопасен" not in rendered
