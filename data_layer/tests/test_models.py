"""Tests for data layer models and static providers."""

from __future__ import annotations

from datetime import datetime, timezone

from data_layer import DataBatch, DataItem
from data_layer.providers import MarketDataProvider, RSSProvider


def test_data_item_creation() -> None:
    """DataItem stores provided fields."""

    timestamp = datetime.now(timezone.utc)
    item = DataItem(
        source="source",
        category="news",
        title="Title",
        content="Content",
        url="https://example.com",
        published_at=timestamp,
        metadata={"key": "value"},
    )

    assert item.source == "source"
    assert item.category == "news"
    assert item.title == "Title"
    assert item.content == "Content"
    assert item.url == "https://example.com"
    assert item.published_at == timestamp
    assert item.metadata == {"key": "value"}


def test_data_batch_creation() -> None:
    """DataBatch stores item lists."""

    item = _item()
    batch = DataBatch(items=[item])

    assert batch.items == [item]


def test_rss_provider_name() -> None:
    """RSS provider returns its name."""

    provider = RSSProvider(items=[])

    assert provider.name() == "RSSProvider"


def test_rss_provider_fetch() -> None:
    """RSS provider returns configured static items."""

    item = _item()
    provider = RSSProvider(items=[item])

    assert provider.fetch().items == [item]


def test_market_provider_name() -> None:
    """Market data provider returns its name."""

    provider = MarketDataProvider(items=[])

    assert provider.name() == "MarketDataProvider"


def test_market_provider_fetch() -> None:
    """Market data provider returns configured static items."""

    item = _item()
    provider = MarketDataProvider(items=[item])

    assert provider.fetch().items == [item]


def _item() -> DataItem:
    """Create a test data item."""

    return DataItem(
        source="test",
        category="market",
        title="Test",
        content="Content",
        url=None,
        published_at=None,
        metadata={},
    )
