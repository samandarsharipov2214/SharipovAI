from news_monitor.event_identity import (
    cluster_news_events,
    event_id_for_item,
    normalize_headline,
    publication_day,
)


def _item(
    *,
    title="Bitcoin ETF inflows rise",
    family="publisher-a",
    source_id="feed-a",
    published_at="2026-08-19T10:00:00+00:00",
    provenance_id="prov-a",
    trust_score=0.8,
    url="https://example.com/a",
):
    return {
        "title": title,
        "source_family": family,
        "source_id": source_id,
        "published_at": published_at,
        "provenance_id": provenance_id,
        "trust_score": trust_score,
        "url": url,
        "summary": "raw summary that must not be copied into compact events",
    }


def test_headline_normalization_and_publication_day_are_deterministic():
    assert normalize_headline("  Bitcoin &amp; ETF:  INFLOWS! ") == "bitcoin etf inflows"
    assert publication_day("2026-08-19T23:30:00-04:00") == "2026-08-20"
    assert publication_day("not-a-time") == ""


def test_same_normalized_headline_and_day_share_event_id_across_sources():
    first = _item(title="Bitcoin ETF inflows rise")
    second = _item(
        title="BITCOIN ETF — inflows rise!",
        family="publisher-b",
        source_id="feed-b",
        provenance_id="prov-b",
        url="https://example.net/b",
    )

    assert event_id_for_item(first) == event_id_for_item(second)


def test_repeated_syndication_from_one_family_does_not_inflate_source_family_count():
    result = cluster_news_events(
        [
            _item(provenance_id="prov-a1", source_id="feed-a1"),
            _item(provenance_id="prov-a2", source_id="feed-a2", url="https://example.com/a2"),
        ]
    )

    assert result["event_count"] == 1
    event = result["events"][0]
    assert event["item_count"] == 2
    assert event["source_family_count"] == 1
    assert event["source_families"] == ("publisher-a",)
    assert event["provenance_ids"] == ("prov-a1", "prov-a2")


def test_distinct_source_families_are_counted_without_claiming_more_events():
    result = cluster_news_events(
        [
            _item(family="wire-a", provenance_id="prov-wire"),
            _item(
                family="official-filing",
                source_id="official-feed",
                provenance_id="prov-official",
                trust_score=0.95,
                url="https://official.example/item",
            ),
        ]
    )

    assert result["event_count"] == 1
    event = result["events"][0]
    assert event["source_family_count"] == 2
    assert event["source_families"] == ("official-filing", "wire-a")
    assert event["representative_url"] == "https://official.example/item"
    assert event["representative_trust_score"] == 0.95


def test_same_headline_on_different_utc_days_is_not_silently_collapsed():
    first = _item(published_at="2026-08-19T10:00:00+00:00")
    second = _item(
        published_at="2026-08-20T10:00:00+00:00",
        provenance_id="prov-b",
    )

    assert event_id_for_item(first) != event_id_for_item(second)
    assert cluster_news_events([first, second])["event_count"] == 2


def test_compact_events_do_not_copy_raw_summary_and_processing_is_bounded():
    items = [
        _item(title=f"Event {index}", provenance_id=f"prov-{index}")
        for index in range(5)
    ]
    result = cluster_news_events(items, max_items=3)

    assert result["input_item_count"] == 5
    assert result["processed_item_count"] == 3
    assert result["event_count"] == 3
    assert result["truncated"] is True
    assert result["max_items"] == 3
    assert all("summary" not in event for event in result["events"])


def test_titleless_item_falls_back_to_provenance_identity_and_missing_identity_fails():
    item = _item(title="", provenance_id="prov-only")
    assert event_id_for_item(item) == event_id_for_item(dict(item))

    broken = _item(title="", provenance_id="")
    try:
        event_id_for_item(broken)
    except ValueError as exc:
        assert "title or provenance_id" in str(exc)
    else:
        raise AssertionError("missing news identity must fail closed")
