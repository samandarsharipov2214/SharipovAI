"""In-memory cache implementation for the data layer."""

from __future__ import annotations

from typing import Any


class InMemoryCache:
    """Simple in-memory key-value cache."""

    def __init__(self) -> None:
        """Initialize an empty cache."""

        self._items: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Store a value by key.

        Args:
            key: Cache key.
            value: Value to store.
        """

        self._items[key] = value

    def get(self, key: str) -> Any:
        """Get a value by key.

        Args:
            key: Cache key.

        Returns:
            Stored value, or ``None`` when the key does not exist.
        """

        return self._items.get(key)

    def delete(self, key: str) -> None:
        """Delete a value by key.

        Args:
            key: Cache key.
        """

        self._items.pop(key, None)

    def clear(self) -> None:
        """Clear all cached values."""

        self._items.clear()

    def exists(self, key: str) -> bool:
        """Return whether a key exists.

        Args:
            key: Cache key.

        Returns:
            ``True`` when the key exists.
        """

        return key in self._items
