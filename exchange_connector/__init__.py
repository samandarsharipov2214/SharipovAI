"""Safe exchange connector layer for SharipovAI.

The connector is intentionally safety-first: it can read configuration and build
order previews, but real execution is blocked unless explicit guard flags are
configured in the environment.
"""

from __future__ import annotations

from .models import ExchangeConfig, ExchangeOrderPreview, ExchangeStatus
from .safe_client import SafeExchangeConnector

__all__ = (
    "ExchangeConfig",
    "ExchangeOrderPreview",
    "ExchangeStatus",
    "SafeExchangeConnector",
)
