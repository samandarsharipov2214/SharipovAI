"""Tests for the in-memory cache."""

from __future__ import annotations

from data_layer import InMemoryCache


def test_cache_set_get() -> None:
    """Cache stores and retrieves values."""

    cache = InMemoryCache()
    cache.set("key", {"value": 1})

    assert cache.get("key") == {"value": 1}
    assert cache.exists("key") is True


def test_cache_delete() -> None:
    """Cache deletes values."""

    cache = InMemoryCache()
    cache.set("key", "value")
    cache.delete("key")

    assert cache.get("key") is None
    assert cache.exists("key") is False


def test_cache_clear() -> None:
    """Cache clears all values."""

    cache = InMemoryCache()
    cache.set("first", 1)
    cache.set("second", 2)
    cache.clear()

    assert cache.exists("first") is False
    assert cache.exists("second") is False
