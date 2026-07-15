"""Tests for RSS reader."""
from __future__ import annotations

from types import SimpleNamespace

import httpx

import news_monitor.rss_reader as rss_reader


def test_rss_status_lists_allowlisted_sources() -> None:
    status = rss_reader.rss_status()

    assert status["enabled"] is True
    assert status["source_count"] >= 1
    assert status["sources"]


def test_read_rss_items_normalizes_feed_entries_without_network(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        content = b"<rss><channel><item/></channel></rss>"
        headers = {"content-type": "application/rss+xml"}

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        def get(self, url: str) -> FakeResponse:
            assert url.startswith("https://")
            return FakeResponse()

    def fake_parse(content: bytes) -> SimpleNamespace:
        assert content == FakeResponse.content
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

    monkeypatch.setattr(rss_reader.httpx, "Client", FakeClient)
    monkeypatch.setattr(rss_reader.feedparser, "parse", fake_parse)

    result = rss_reader.read_rss_items(limit_per_source=1)

    assert result["status"] == "ok"
    assert result["items"]
    assert all(item["kind"] == "rss" for item in result["items"])
    assert all("BTC" in item["title"] for item in result["items"])
    assert result["errors"] == []
    assert result["diagnostics"]["working_sources"] == result["rss"]["source_count"]


def test_http_error_is_reported_without_synthetic_fallback(monkeypatch) -> None:
    request = httpx.Request("GET", "https://example.com/feed")
    response = httpx.Response(503, request=request)

    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        def get(self, url: str):
            del url
            return response

    monkeypatch.setattr(rss_reader.httpx, "Client", FailingClient)
    result = rss_reader.read_rss_items(limit_per_source=1)

    assert result["status"] == "empty"
    assert result["items"] == []
    assert result["errors"]
    assert all(item["http_status"] == "503" for item in result["errors"])
