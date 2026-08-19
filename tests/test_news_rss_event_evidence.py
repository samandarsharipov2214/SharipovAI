from __future__ import annotations

from dataclasses import dataclass

from news_monitor import rss_reader


@dataclass(frozen=True)
class _Source:
    id: str
    name: str
    url: str
    trust_score: float
    kind: str = "rss"
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "trust_score": self.trust_score,
            "kind": self.kind,
            "enabled": self.enabled,
        }


def test_read_rss_items_exposes_bounded_event_view_without_dropping_raw_items(monkeypatch):
    sources = [
        _Source("reuters_primary", "Reuters Primary", "https://example.test/reuters-1.xml", 0.9),
        _Source("reuters_mirror", "Reuters Mirror", "https://example.test/reuters-2.xml", 0.8),
        _Source("ap_primary", "AP Primary", "https://example.test/ap.xml", 0.85),
    ]
    monkeypatch.setattr(rss_reader, "default_sources", lambda: sources)

    def fake_read(source: _Source, limit: int) -> dict[str, object]:
        assert limit == 1
        family = "reuters" if source.id.startswith("reuters") else "ap"
        item = {
            "source_id": source.id,
            "source_name": source.name,
            "source_family": family,
            "source_feed_url": source.url,
            "kind": "rss",
            "title": "Central bank keeps rates unchanged",
            "summary": "raw summary must stay only on the raw item",
            "url": f"https://example.test/{source.id}/story",
            "trust_score": source.trust_score,
            "published_at": "2026-08-19T12:00:00+00:00",
            "fetched_at": "2026-08-19T12:01:00+00:00",
            "timestamp_quality": "source_timestamp",
            "provenance_id": f"prov-{source.id}",
        }
        return {
            "source_id": source.id,
            "source_name": source.name,
            "status": "ok",
            "http_status": 200,
            "item_count": 1,
            "items": [item],
            "error": "",
        }

    monkeypatch.setattr(rss_reader, "_read_one_source", fake_read)

    response = rss_reader.read_rss_items(limit_per_source=1)

    assert response["status"] == "ok"
    assert len(response["items"]) == 3
    assert len(response["events"]) == 1

    event = response["events"][0]
    assert event["item_count"] == 3
    assert event["source_family_count"] == 2
    assert event["source_families"] == ("ap", "reuters")
    assert set(event["provenance_ids"]) == {
        "prov-ap_primary",
        "prov-reuters_primary",
        "prov-reuters_mirror",
    }
    assert "summary" not in event

    diagnostics = response["diagnostics"]
    assert diagnostics["item_count"] == 3
    assert diagnostics["event_count"] == 1
    assert diagnostics["event_items_processed"] == 3
    assert diagnostics["event_items_truncated"] is False
    assert diagnostics["event_max_items"] == 512
