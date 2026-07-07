"""Static RSS data provider.

This provider accepts static data items and performs no network calls.
"""

from __future__ import annotations

from data_layer.models import DataBatch, DataItem

from .base import BaseDataProvider


class RSSProvider(BaseDataProvider):
    """Static RSS-style data provider."""

    PROVIDER_NAME: str = "RSSProvider"

    def __init__(self, items: list[DataItem]) -> None:
        """Initialize the provider.

        Args:
            items: Static data items returned by ``fetch``.
        """

        self._items = list(items)

    def name(self) -> str:
        """Return the provider name."""

        return self.PROVIDER_NAME

    def fetch(self) -> DataBatch:
        """Fetch static RSS data.

        Returns:
            Data batch containing configured static items.
        """

        return DataBatch(items=list(self._items))
