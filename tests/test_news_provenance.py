from datetime import UTC, datetime, timedelta

from news_monitor.provenance import (
    MAX_FUTURE_SKEW,
    normalize_publication_timestamp,
    provenance_fields,
)


def test_source_timestamp_is_normalized_to_utc_without_losing_origin_time():
    fetched = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    published, quality = normalize_publication_timestamp(
        "2026-08-19T13:55:00+02:00",
        fetched_at=fetched,
    )

    assert published == "2026-08-19T11:55:00+00:00"
    assert quality == "source_timestamp"


def test_missing_or_invalid_timestamp_fails_closed_to_fetch_time():
    fetched = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    for raw in ("", "not-a-timestamp"):
        published, quality = normalize_publication_timestamp(raw, fetched_at=fetched)
        assert published == "2026-08-19T12:00:00+00:00"
        assert quality == "fetch_fallback_missing_or_invalid"


def test_implausible_future_timestamp_fails_closed_to_fetch_time():
    fetched = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    future = fetched + MAX_FUTURE_SKEW + timedelta(seconds=1)

    published, quality = normalize_publication_timestamp(future.isoformat(), fetched_at=fetched)

    assert published == fetched.isoformat()
    assert quality == "fetch_fallback_future_skew"


def test_provenance_fields_are_compact_stable_and_source_scoped():
    fetched = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    kwargs = {
        "source_id": "reuters_markets",
        "source_name": "Reuters Markets",
        "source_feed_url": "https://example.test/feed.xml",
        "item_url": "https://example.test/story/1",
        "published_at": "2026-08-19T11:59:00Z",
        "fetched_at": fetched,
    }

    first = provenance_fields(**kwargs)
    second = provenance_fields(**kwargs)
    other = provenance_fields(**{**kwargs, "source_id": "other_family"})

    assert first == second
    assert first["source_family"] == "reuters_markets"
    assert first["source_feed_url"] == "https://example.test/feed.xml"
    assert first["published_at"] == "2026-08-19T11:59:00+00:00"
    assert first["fetched_at"] == "2026-08-19T12:00:00+00:00"
    assert first["timestamp_quality"] == "source_timestamp"
    assert len(first["provenance_id"]) == 64
    assert other["provenance_id"] != first["provenance_id"]
    assert set(first) == {
        "source_family",
        "source_feed_url",
        "source_name",
        "published_at",
        "fetched_at",
        "timestamp_quality",
        "provenance_id",
    }
