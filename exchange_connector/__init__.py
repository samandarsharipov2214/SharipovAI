"""Safe exchange connector layer for SharipovAI.

Public market/account reads and previews are allowed. Exchange-bound writes must
use the canonical execution contract, and mainnet execution is compiled out.
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
from .execution_contract import (
    ApprovedExecutionRequest,
    MAINNET_EXECUTION_COMPILED,
    build_execution_request,
    validate_execution_request,
)
from .execution_idempotency import (
    DuplicateExecutionBlocked,
    ExecutionIdempotencyRepository,
)
from .models import ExchangeConfig, ExchangeOrderPreview, ExchangeStatus
from .safe_client import SafeExchangeConnector

__all__ = (
    "ApprovedExecutionRequest",
    "DuplicateExecutionBlocked",
    "ExchangeConfig",
    "ExchangeOrderPreview",
    "ExchangeStatus",
    "ExecutionIdempotencyRepository",
    "MAINNET_EXECUTION_COMPILED",
    "SafeExchangeConnector",
    "ai_cost_report",
    "best_trade_venue",
    "borrow_table",
    "build_execution_request",
    "estimate_borrow_cost",
    "estimate_trade_cost",
    "fee_table",
    "select_fee_rate",
    "validate_execution_request",
    "vip_progress",
)
