"""Risk-based capital allocation for the SharipovAI virtual account.

The allocator increases position size with account equity while preserving a
configurable cash reserve.  It is deliberately leverage-free and contains no
exchange write operations.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CapitalAllocationPolicy:
    """Bounded policy for virtual-account exposure."""

    reserve_percent: float = 20.0
    max_position_percent: float = 20.0
    max_risk_per_trade_percent: float = 1.0
    minimum_notional: float = 25.0
    leverage: float = 1.0

    @classmethod
    def from_environment(cls) -> "CapitalAllocationPolicy":
        return cls(
            reserve_percent=_bounded_env("VIRTUAL_ACCOUNT_RESERVE_PERCENT", 20.0, 5.0, 50.0),
            max_position_percent=_bounded_env("VIRTUAL_ACCOUNT_MAX_POSITION_PERCENT", 20.0, 5.0, 50.0),
            max_risk_per_trade_percent=_bounded_env(
                "VIRTUAL_ACCOUNT_MAX_RISK_PER_TRADE_PERCENT",
                1.0,
                0.25,
                2.0,
            ),
            minimum_notional=_bounded_env("VIRTUAL_ACCOUNT_MIN_NOTIONAL_USDT", 25.0, 1.0, 1_000.0),
            leverage=1.0,
        )

    def snapshot(self) -> dict[str, float]:
        return asdict(self)


def build_capital_allocation(
    *,
    equity: float,
    open_trades: Sequence[Mapping[str, Any]],
    max_open_positions: int,
    stop_loss_percent: float,
    fee_rate: float,
    requested_risk_percent: float,
    policy: CapitalAllocationPolicy | None = None,
) -> dict[str, Any]:
    """Return a deterministic no-leverage allocation plan.

    The deployable amount is divided by the remaining position slots.  A single
    position is additionally capped by account percentage and by the amount that
    can be lost at the configured stop including estimated round-trip fees.
    """

    policy = policy or CapitalAllocationPolicy.from_environment()
    clean_equity = max(0.0, float(equity or 0.0))
    position_limit = max(1, int(max_open_positions or 1))
    active = [item for item in open_trades if str(item.get("status", "OPEN")).upper() == "OPEN"]
    deployed_notional = round(
        sum(max(0.0, float(item.get("notional", 0.0) or 0.0)) for item in active),
        4,
    )
    reserve_amount = round(clean_equity * policy.reserve_percent / 100.0, 4)
    deployable_capital = round(max(0.0, clean_equity - reserve_amount), 4)
    available_to_allocate = round(max(0.0, deployable_capital - deployed_notional), 4)
    remaining_slots = max(0, position_limit - len(active))

    requested_risk = max(0.0, float(requested_risk_percent or 0.0))
    effective_risk_percent = min(requested_risk, policy.max_risk_per_trade_percent)
    stop_distance_percent = max(0.01, float(stop_loss_percent or 0.0))
    round_trip_fee_percent = max(0.0, float(fee_rate or 0.0)) * 2.0 * 100.0
    loss_distance_fraction = (stop_distance_percent + round_trip_fee_percent) / 100.0
    risk_budget = round(clean_equity * effective_risk_percent / 100.0, 4)
    risk_notional_cap = round(risk_budget / loss_distance_fraction, 4) if loss_distance_fraction > 0 else 0.0
    position_notional_cap = round(clean_equity * policy.max_position_percent / 100.0, 4)
    equal_slot_budget = round(available_to_allocate / remaining_slots, 4) if remaining_slots > 0 else 0.0
    notional = round(min(equal_slot_budget, position_notional_cap, risk_notional_cap), 2)

    reason = "allocated"
    allowed = True
    if clean_equity <= 0:
        reason = "equity_unavailable"
        allowed = False
    elif remaining_slots <= 0:
        reason = "position_limit_reached"
        allowed = False
    elif available_to_allocate < policy.minimum_notional:
        reason = "reserve_protected"
        allowed = False
    elif effective_risk_percent <= 0:
        reason = "risk_budget_unavailable"
        allowed = False
    elif notional < policy.minimum_notional:
        reason = "allocation_below_minimum"
        allowed = False

    if not allowed:
        notional = 0.0

    utilization_percent = round(deployed_notional / clean_equity * 100.0, 4) if clean_equity > 0 else 0.0
    projected_utilization_percent = (
        round((deployed_notional + notional) / clean_equity * 100.0, 4) if clean_equity > 0 else 0.0
    )
    return {
        "status": "ok" if allowed else "blocked",
        "allowed": allowed,
        "reason": reason,
        "notional": notional,
        "equity": round(clean_equity, 4),
        "reserve_percent": policy.reserve_percent,
        "reserve_amount": reserve_amount,
        "deployable_capital": deployable_capital,
        "deployed_notional": deployed_notional,
        "available_to_allocate": available_to_allocate,
        "remaining_slots": remaining_slots,
        "equal_slot_budget": equal_slot_budget,
        "position_notional_cap": position_notional_cap,
        "risk_notional_cap": risk_notional_cap,
        "risk_budget": risk_budget,
        "requested_risk_percent": requested_risk,
        "effective_risk_percent": effective_risk_percent,
        "estimated_round_trip_fee_percent": round(round_trip_fee_percent, 6),
        "stop_loss_percent": stop_distance_percent,
        "utilization_percent": utilization_percent,
        "projected_utilization_percent": projected_utilization_percent,
        "leverage": policy.leverage,
        "policy": policy.snapshot(),
    }


def capital_snapshot(
    *,
    equity: float,
    open_trades: Sequence[Mapping[str, Any]],
    policy: CapitalAllocationPolicy | None = None,
) -> dict[str, Any]:
    """Summarize current exposure without planning a new trade."""

    policy = policy or CapitalAllocationPolicy.from_environment()
    clean_equity = max(0.0, float(equity or 0.0))
    deployed = round(
        sum(max(0.0, float(item.get("notional", 0.0) or 0.0)) for item in open_trades),
        4,
    )
    reserve = round(clean_equity * policy.reserve_percent / 100.0, 4)
    deployable = round(max(0.0, clean_equity - reserve), 4)
    available = round(max(0.0, deployable - deployed), 4)
    return {
        "equity": round(clean_equity, 4),
        "deployed_notional": deployed,
        "reserve_amount": reserve,
        "reserve_percent": policy.reserve_percent,
        "deployable_capital": deployable,
        "available_to_allocate": available,
        "capital_utilization_percent": round(deployed / clean_equity * 100.0, 4) if clean_equity > 0 else 0.0,
        "deployable_utilization_percent": round(deployed / deployable * 100.0, 4) if deployable > 0 else 0.0,
        "leverage": policy.leverage,
    }


def _bounded_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return round(min(max(value, minimum), maximum), 6)


__all__ = ["CapitalAllocationPolicy", "build_capital_allocation", "capital_snapshot"]
