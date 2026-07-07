"""Base interface for data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from data_layer.models import DataBatch


class BaseDataProvider(ABC):
    """Abstract base class for data providers."""

    @abstractmethod
    def name(self) -> str:
        """Return the provider name.

        Returns:
            Provider name.
        """

    @abstractmethod
    def fetch(self) -> DataBatch:
        """Fetch data from the provider.

        Returns:
            Data batch.
        """
