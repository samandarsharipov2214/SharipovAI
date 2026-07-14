"""Realistic deterministic fee, spread and slippage calculations."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .models import MarketEvent, Side


@dataclass(frozen=True, slots=True)
class ExecutionCost:
    reference_price: float
    execution_price: float
    fee: float
    slippage_cost: float


@dataclass(frozen=True, slots=True)
class ExecutionCostModel:
    fee_rate: float = 0.001
    slippage_bps: float = 2.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.fee_rate) or not 0 <= self.fee_rate <= 0.05:
            raise ValueError("fee_rate must be within 0..0.05")
        if not math.isfinite(self.slippage_bps) or not 0 <= self.slippage_bps <= 1_000:
            raise ValueError("slippage_bps must be within 0..1000")

    def estimate(
        self,
        event: MarketEvent,
        *,
        side: Side,
        quantity: float,
    ) -> ExecutionCost:
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("quantity must be positive and finite")
        reference = event.ask if side is Side.BUY else event.bid
        multiplier = 1.0 + self.slippage_bps / 10_000.0
        execution = reference * multiplier if side is Side.BUY else reference / multiplier
        notional = execution * quantity
        fee = notional * self.fee_rate
        slippage = abs(execution - reference) * quantity
        return ExecutionCost(
            reference_price=reference,
            execution_price=execution,
            fee=fee,
            slippage_cost=slippage,
        )


def validate_market_event(event: MarketEvent) -> None:
    if not isinstance(event.timestamp_ms, int) or event.timestamp_ms <= 0:
        raise ValueError("market event timestamp_ms must be positive")
    if not event.symbol or event.symbol != event.symbol.upper() or not event.symbol.isalnum():
        raise ValueError("market event symbol must be uppercase alphanumeric")
    for name, value in (("bid", event.bid), ("ask", event.ask)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"market event {name} must be positive and finite")
    if event.ask < event.bid:
        raise ValueError("market event ask must not be below bid")
    if not str(event.source).strip():
        raise ValueError("market event source is required")


__all__ = ["ExecutionCost", "ExecutionCostModel", "validate_market_event"]
