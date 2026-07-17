"""Deterministic fee, spread, slippage and market-impact calculations."""
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
    spread_cost: float = 0.0
    participation_rate: float = 0.0
    effective_slippage_bps: float = 0.0
    fee_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class ExecutionCostModel:
    """Model taker/maker fees and nonlinear impact without random fills."""

    fee_rate: float = 0.001
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    market_impact_bps: float = 15.0
    max_participation_rate: float = 0.10

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("fee_rate", self.fee_rate, 0.05),
            ("maker_fee_rate", self.maker_fee_rate, 0.05),
            ("slippage_bps", self.slippage_bps, 1_000.0),
            ("market_impact_bps", self.market_impact_bps, 10_000.0),
            ("max_participation_rate", self.max_participation_rate, 1.0),
        ):
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"{name} must be within 0..{maximum}")
        if self.max_participation_rate <= 0:
            raise ValueError("max_participation_rate must be positive")

    def estimate(
        self,
        event: MarketEvent,
        *,
        side: Side,
        quantity: float,
        liquidity_role: str = "taker",
    ) -> ExecutionCost:
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("quantity must be positive and finite")

        role = str(liquidity_role or "taker").strip().lower()
        if role not in {"maker", "taker"}:
            raise ValueError("liquidity_role must be maker or taker")

        participation = 0.0
        if event.volume is not None:
            if not math.isfinite(event.volume) or event.volume <= 0:
                raise ValueError("market event volume must be positive when provided")
            participation = quantity / event.volume
            if participation > self.max_participation_rate:
                raise ValueError(
                    "order participation exceeds configured market-liquidity limit"
                )

        reference = event.ask if side is Side.BUY else event.bid
        spread_cost = abs(reference - event.mid) * quantity
        impact_bps = self.market_impact_bps * math.sqrt(max(0.0, participation))
        effective_bps = self.slippage_bps + impact_bps
        multiplier = 1.0 + effective_bps / 10_000.0
        execution = reference * multiplier if side is Side.BUY else reference / multiplier
        notional = execution * quantity
        applied_fee_rate = self.maker_fee_rate if role == "maker" else self.fee_rate
        fee = notional * applied_fee_rate
        slippage = abs(execution - reference) * quantity
        return ExecutionCost(
            reference_price=reference,
            execution_price=execution,
            fee=fee,
            slippage_cost=slippage,
            spread_cost=spread_cost,
            participation_rate=participation,
            effective_slippage_bps=effective_bps,
            fee_rate=applied_fee_rate,
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
    if event.volume is not None and (
        not math.isfinite(event.volume) or event.volume <= 0
    ):
        raise ValueError("market event volume must be positive and finite")
    if not math.isfinite(event.funding_rate) or abs(event.funding_rate) > 0.10:
        raise ValueError("market event funding_rate must be finite and within +/-10%")
    if (
        not math.isfinite(event.funding_interval_hours)
        or event.funding_interval_hours <= 0
        or event.funding_interval_hours > 24 * 31
    ):
        raise ValueError("funding_interval_hours must be within 0..744")


__all__ = ["ExecutionCost", "ExecutionCostModel", "validate_market_event"]
