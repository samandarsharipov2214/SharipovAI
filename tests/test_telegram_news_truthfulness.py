from __future__ import annotations

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


def test_invalid_credibility_does_not_render_as_a_real_percentage() -> None:
    for credibility in ("unknown", False, True):
        rendered = format_news_item(
            {
                "title": "Market update",
                "source_name": "Example Wire",
                "credibility_percent": credibility,
            },
            index=3,
        )

        assert "достоверность не указана" in rendered
        assert f"{credibility}%" not in rendered
        assert "достоверность <b>0%</b>" not in rendered
        assert "достоверность <b>1%</b>" not in rendered
