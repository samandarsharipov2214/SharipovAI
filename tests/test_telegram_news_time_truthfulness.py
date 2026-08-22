from __future__ import annotations

from telegram_presentation import format_news_item, format_news_time


def test_malformed_news_time_is_explicitly_unconfirmed() -> None:
    rendered = format_news_time("not-a-timestamp")

    assert rendered == "время публикации некорректно; свежесть не подтверждена"
    assert "not-a-timestamp" not in rendered


def test_source_timestamp_quality_does_not_make_malformed_time_look_confirmed() -> None:
    rendered = format_news_item(
        {
            "title": "Market update",
            "source_name": "Example Wire",
            "published_at": "not-a-timestamp",
            "timestamp_quality": "source_timestamp",
        },
        index=1,
    )

    assert "время публикации некорректно; свежесть не подтверждена" in rendered
    assert "not-a-timestamp" not in rendered
