"""Bybit V5 market-data client package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .exceptions import BybitAPIError, BybitClientError, BybitHTTPError
from .models import BybitResponse, InstrumentInfo, ServerTime, TickerInfo

if TYPE_CHECKING:
    from .client import BybitClient

__all__: tuple[str, ...] = (
    "BybitAPIError",
    "BybitClient",
    "BybitClientError",
    "BybitHTTPError",
    "BybitResponse",
    "InstrumentInfo",
    "ServerTime",
    "TickerInfo",
)


def __getattr__(name: str) -> Any:
    """Load optional package exports on demand.

    Args:
        name: Requested export name.

    Returns:
        Requested package attribute.

    Raises:
        AttributeError: If the requested name is not exported.
    """

    if name == "BybitClient":
        from .client import BybitClient

        return BybitClient

    raise AttributeError(f"module 'bybit' has no attribute '{name}'")
