"""Safe exchange connector layer for SharipovAI.

The connector is intentionally safety-first: it can read configuration and build
order previews, but real execution is blocked unless explicit guard flags are
configured in the environment.
"""

from __future__ import annotations

from .bybit_costs import (
    ai_cost_report,
    best_trade_venue,
    borrow_table,
    estimate_borrow_cost,
    estimate_trade_cost,
    fee_table,
    select_fee_rate,
    vip_progress,
)
from .models import ExchangeConfig, ExchangeOrderPreview, ExchangeStatus
from .safe_client import SafeExchangeConnector

__all__ = (
    "ExchangeConfig",
    "ExchangeOrderPreview",
    "ExchangeStatus",
    "SafeExchangeConnector",
    "ai_cost_report",
    "best_trade_venue",
    "borrow_table",
    "estimate_borrow_cost",
    "estimate_trade_cost",
    "fee_table",
    "select_fee_rate",
    "vip_progress",
)
