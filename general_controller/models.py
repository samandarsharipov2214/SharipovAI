from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentReport:
    agent: str
    status: str
    recommendation: str
    checked_at: int
    valid_until: int
    confidence: float | None = None
    risk_level: str | None = None
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalDecision:
    decision_id: str
    decision: str
    symbol: str
    created_at: int
    valid_until: int
    confidence: float | None
    risk_level: str
    position_size_usdt: float
    entry_conditions: list[str]
    exit_conditions: list[str]
    stop_loss_percent: float | None
    take_profit_percent: float | None
    max_holding_seconds: int | None
    supporting_agents: list[str]
    opposing_agents: list[str]
    evidence: list[str]
    blockers: list[str]
    reason_ru: str
    system_status: str
    owner_approval_required: bool
    real_orders_allowed: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
