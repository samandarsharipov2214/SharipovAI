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
from .bybit_execution_state import BybitExecutionStateStore, ExecutionFill
from .bybit_reference_data import (
    BybitTradingReferenceClient,
    FeeSchedule,
    InstrumentRules,
    TradingReferenceSnapshot,
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
from .execution_kill_switch import KillSwitchState, PersistentExecutionKillSwitch
from .models import ExchangeConfig, ExchangeOrderPreview, ExchangeStatus
from .private_ws_gate import PrivateStreamGateReport, PrivateStreamHealthRepository
from .safe_client import SafeExchangeConnector

__all__ = (
    "ApprovedExecutionRequest",
    "BybitExecutionStateStore",
    "BybitTradingReferenceClient",
    "DuplicateExecutionBlocked",
    "ExchangeConfig",
    "ExchangeOrderPreview",
    "ExchangeStatus",
    "ExecutionFill",
    "ExecutionIdempotencyRepository",
    "FeeSchedule",
    "InstrumentRules",
    "KillSwitchState",
    "MAINNET_EXECUTION_COMPILED",
    "PersistentExecutionKillSwitch",
    "PrivateStreamGateReport",
    "PrivateStreamHealthRepository",
    "SafeExchangeConnector",
    "TradingReferenceSnapshot",
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
