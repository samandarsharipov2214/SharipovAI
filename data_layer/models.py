"""Typed models for data layer records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DataItem:
    """Single data item collected by a data provider.

    Attributes:
        source: Data source name.
        category: Data category.
        title: Item title.
        content: Item content.
        url: Optional item URL.
        published_at: Optional publication timestamp.
        metadata: Additional structured metadata.
    """

    source: str
    category: str
    title: str
    content: str
    url: str | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataBatch:
    """Batch of data items returned by a provider.

    Attributes:
        items: Data items in the batch.
    """

    items: list[DataItem] = field(default_factory=list)
