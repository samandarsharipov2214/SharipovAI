from datetime import UTC, datetime

import pytest

from news_monitor.provenance import normalize_public_url, provenance_fields


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//example.com/article",
        "/relative/article",
        "https:///missing-host",
        "https://example.com:99999/article",
        "",
    ],
)
def test_normalize_public_url_rejects_unsafe_or_non_absolute_values(value: str) -> None:
    assert normalize_public_url(value) == ""


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/article?id=42#section",
        "http://news.example.org:8080/path",
    ],
)
def test_normalize_public_url_preserves_valid_http_urls(value: str) -> None:
    assert normalize_public_url(value) == value


def test_provenance_does_not_emit_unsafe_feed_url_or_hash_unsafe_item_url() -> None:
    fetched_at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    unsafe = provenance_fields(
        source_id="feed-a",
        source_name="Feed A",
        source_feed_url="javascript:alert(1)",
        item_url="data:text/html,unsafe",
        published_at="2026-08-20T11:00:00+00:00",
        fetched_at=fetched_at,
    )
    blank = provenance_fields(
        source_id="feed-a",
        source_name="Feed A",
        source_feed_url="",
        item_url="",
        published_at="2026-08-20T11:00:00+00:00",
        fetched_at=fetched_at,
    )

    assert unsafe["source_feed_url"] == ""
    assert unsafe["provenance_id"] == blank["provenance_id"]
