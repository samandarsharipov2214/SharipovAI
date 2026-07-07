"""Tests for the live RSS provider."""

from __future__ import annotations

from types import SimpleNamespace
from time import struct_time
from unittest.mock import patch

from data_layer.providers import LiveRSSProvider


def test_live_rss_provider_name() -> None:
    """Live RSS provider returns its name."""

    provider = LiveRSSProvider(feed_urls=[])

    assert provider.name() == "LiveRSSProvider"


def test_live_rss_provider_fetch_parses_entries() -> None:
    """Live RSS provider converts parsed entries into data items."""

    published = struct_time((2026, 7, 7, 12, 0, 0, 1, 188, 0))
    parsed_feed = SimpleNamespace(
        bozo=False,
        feed={"title": "Example Feed"},
        entries=[
            {
                "title": "Bitcoin ETF Approval",
                "summary": "ETF approval news.",
                "link": "https://example.com/news",
                "published_parsed": published,
                "id": "entry-1",
                "author": "Reporter",
                "tags": [{"term": "bitcoin"}, {"term": "etf"}],
            }
        ],
    )

    with patch("data_layer.providers.live_rss_provider._parse_feed") as parse:
        parse.return_value = parsed_feed
        batch = LiveRSSProvider(feed_urls=["https://example.com/rss"]).fetch()

    assert len(batch.items) == 1
    item = batch.items[0]
    assert item.source == "Example Feed"
    assert item.category == "rss"
    assert item.title == "Bitcoin ETF Approval"
    assert item.content == "ETF approval news."
    assert item.url == "https://example.com/news"
    assert item.published_at is not None
    assert item.metadata["feed_url"] == "https://example.com/rss"
    assert item.metadata["id"] == "entry-1"
    assert item.metadata["author"] == "Reporter"
    assert item.metadata["tags"] == ["bitcoin", "etf"]


def test_live_rss_provider_skips_bad_feed_and_returns_good_items() -> None:
    """A single bad feed does not stop successful feed parsing."""

    good_feed = {
        "bozo": False,
        "feed": {"title": "Good Feed"},
        "entries": [{"title": "Good item", "summary": "Good content"}],
    }

    def parse(url: str) -> object:
        if "bad" in url:
            raise RuntimeError("bad feed")
        return good_feed

    with patch("data_layer.providers.live_rss_provider._parse_feed", side_effect=parse):
        batch = LiveRSSProvider(
            feed_urls=["https://example.com/bad.xml", "https://example.com/good.xml"]
        ).fetch()

    assert len(batch.items) == 1
    assert batch.items[0].title == "Good item"


def test_live_rss_provider_ignores_unusable_entries() -> None:
    """Entries without title and content are ignored."""

    parsed_feed = {
        "bozo": False,
        "feed": {"title": "Feed"},
        "entries": [{"title": "", "summary": ""}],
    }

    with patch("data_layer.providers.live_rss_provider._parse_feed") as parse:
        parse.return_value = parsed_feed
        batch = LiveRSSProvider(feed_urls=["https://example.com/rss"]).fetch()

    assert batch.items == []
