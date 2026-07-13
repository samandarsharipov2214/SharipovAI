"""Tests for RSS reader."""

from __future__ import annotations

from types import SimpleNamespace

import news_monitor.rss_reader as rss_reader


class _Response:
    status_code = 200
    content = b"<rss><channel><item/></channel></rss>"
    headers = {"content-type": "application/rss+xml"}

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, _url: str) -> _Response:
        return _Response()


def test_rss_status_lists_allowlisted_sources() -> None:
    status = rss_reader.rss_status()
    assert status["enabled"] is True
    assert status["source_count"] >= 1
    assert status["sources"]


def test_read_rss_items_normalizes_feed_entries(monkeypatch) -> None:
    def fake_parse(_payload: bytes) -> SimpleNamespace:
        return SimpleNamespace(
            bozo=False,
            entries=[
                {
                    "title": "BTC ETF inflow update",
                    "summary": "Bitcoin market inflow summary",
                    "link": "https://example.com/btc",
                    "published_parsed": (2026, 1, 2, 3, 4, 5, 0, 0, 0),
                }
            ],
        )

    monkeypatch.setattr(rss_reader.httpx, "Client", _Client)
    monkeypatch.setattr(rss_reader.feedparser, "parse", fake_parse)

    result = rss_reader.read_rss_items(limit_per_source=1)

    assert result["status"] == "ok"
    assert result["items"]
    assert result["items"][0]["kind"] == "rss"
    assert "BTC" in result["items"][0]["title"]
    assert result["errors"] == []
