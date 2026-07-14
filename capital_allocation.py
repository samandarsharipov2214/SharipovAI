"""Risk-based capital allocation shared by paper, backtest and future testnet.

The allocator is deterministic, leverage-free and fail-closed. It preserves a
cash reserve, enforces total/symbol/correlation exposure and sizes positions by
the loss distance after fees. It never performs exchange writes.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

_MAJOR_CRYPTO_SYMBOLS = {
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
}


@dataclass(frozen=True, slots=True)
class CapitalAllocationPolicy:
    """Bounded no-leverage policy for virtual and research environments."""

    reserve_percent: float = 20.0
    max_total_exposure_percent: float = 80.0
    max_position_percent: float = 20.0
    max_symbol_exposure_percent: float = 20.0
    max_correlated_exposure_percent: float = 35.0
    max_risk_per_trade_percent: float = 1.0
    max_daily_loss_percent: float = 2.0
    minimum_notional: float = 25.0
    leverage: float = 1.0

    @classmethod
    def from_environment(cls) -> "CapitalAllocationPolicy":
        reserve = _bounded_env("VIRTUAL_ACCOUNT_RESERVE_PERCENT", 20.0, 5.0, 50.0)
        max_total = _bounded_env(
            "VIRTUAL_ACCOUNT_MAX_TOTAL_EXPOSURE_PERCENT",
            80.0,
            25.0,
            95.0,
        )
        max_total = min(max_total, 100.0 - reserve)
        return cls(
            reserve_percent=reserve,
            max_total_exposure_percent=max_total,
            max_position_percent=_bounded_env(
                "VIRTUAL_ACCOUNT_MAX_POSITION_PERCENT",
                20.0,
                2.0,
                50.0,
            ),
            max_symbol_exposure_percent=_bounded_env(
                "VIRTUAL_ACCOUNT_MAX_SYMBOL_EXPOSURE_PERCENT",
                20.0,
                2.0,
                50.0,
            ),
            max_correlated_exposure_percent=_bounded_env(
                "VIRTUAL_ACCOUNT_MAX_CORRELATED_EXPOSURE_PERCENT",
                35.0,
                5.0,
                80.0,
            ),
            max_risk_per_trade_percent=_bounded_env(
                "VIRTUAL_ACCOUNT_MAX_RISK_PER_TRADE_PERCENT",
                1.0,
                0.10,
                2.0,
            ),
            max_daily_loss_percent=_bounded_env(
                "VIRTUAL_ACCOUNT_MAX_DAILY_LOSS_PERCENT",
                2.0,
                0.25,
                10.0,
            ),
            minimum_notional=_bounded_env(
                "VIRTUAL_ACCOUNT_MIN_NOTIONAL_USDT",
                25.0,
                1.0,
                1_000.0,
            ),
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
    symbol: str = "",
    correlation_group: str = "",
    risk_size_multiplier: float = 1.0,
    current_daily_loss_percent: float = 0.0,
    hard_blocks: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a deterministic allocation plan with hard capital protection.

    Backward-compatible callers can omit the new symbol/risk fields. New callers
    should always pass the target symbol, correlation group and Risk Engine size
    multiplier.
    """

    policy = policy or CapitalAllocationPolicy.from_environment()
    _validate_policy(policy)
    clean_equity = _nonnegative(equity, "equity")
    position_limit = max(1, int(max_open_positions or 1))
    clean_symbol = _symbol(symbol) if symbol else ""
    group = str(correlation_group or "").strip().lower()
    multiplier = _bounded_number(
        risk_size_multiplier,
        "risk_size_multiplier",
        0.0,
        1.0,
    )
    daily_loss = _bounded_number(
        current_daily_loss_percent,
        "current_daily_loss_percent",
        0.0,
        100.0,
    )
    blocks = tuple(sorted({str(item).strip() for item in hard_blocks if str(item).strip()}))

    active = [
        item
        for item in open_trades
        if isinstance(item, Mapping)
        and str(item.get("status", "OPEN")).upper() == "OPEN"
    ]
    deployed_notional = round(sum(_trade_notional(item) for item in active), 4)
    symbol_notional = round(
        sum(
            _trade_notional(item)
            for item in active
            if clean_symbol and _symbol_or_empty(item.get("symbol") or item.get("asset")) == clean_symbol
        ),
        4,
    )
    correlated_notional = round(
        sum(
            _trade_notional(item)
            for item in active
            if group and _trade_group(item) == group
        ),
        4,
    )

    reserve_amount = round(clean_equity * policy.reserve_percent / 100.0, 4)
    reserve_deployable = max(0.0, clean_equity - reserve_amount)
    total_exposure_cap = round(
        clean_equity * policy.max_total_exposure_percent / 100.0,
        4,
    )
    deployable_capital = round(min(reserve_deployable, total_exposure_cap), 4)
    available_to_allocate = round(max(0.0, deployable_capital - deployed_notional), 4)
    remaining_slots = max(0, position_limit - len(active))

    requested_risk = _nonnegative(requested_risk_percent, "requested_risk_percent")
    effective_risk_percent = min(
        requested_risk,
        policy.max_risk_per_trade_percent,
    )
    stop_distance_percent = max(
        0.01,
        _nonnegative(stop_loss_percent, "stop_loss_percent"),
    )
    clean_fee_rate = _nonnegative(fee_rate, "fee_rate")
    round_trip_fee_percent = clean_fee_rate * 2.0 * 100.0
    loss_distance_fraction = (
        stop_distance_percent + round_trip_fee_percent
    ) / 100.0
    risk_budget = round(
        clean_equity * effective_risk_percent / 100.0 * multiplier,
        4,
    )
    risk_notional_cap = round(
        risk_budget / loss_distance_fraction,
        4,
    ) if loss_distance_fraction > 0 else 0.0
    position_notional_cap = round(
        clean_equity * policy.max_position_percent / 100.0,
        4,
    )
    symbol_exposure_cap = round(
        clean_equity * policy.max_symbol_exposure_percent / 100.0,
        4,
    )
    available_symbol = max(0.0, symbol_exposure_cap - symbol_notional)
    correlated_exposure_cap = round(
        clean_equity * policy.max_correlated_exposure_percent / 100.0,
        4,
    )
    available_correlated = (
        max(0.0, correlated_exposure_cap - correlated_notional)
        if group
        else available_to_allocate
    )
    equal_slot_budget = round(
        available_to_allocate / remaining_slots,
        4,
    ) if remaining_slots > 0 else 0.0

    notional = round(
        min(
            available_to_allocate,
            position_notional_cap,
            available_symbol if clean_symbol else position_notional_cap,
            available_correlated,
            risk_notional_cap,
        ),
        2,
    )

    reason = "allocated"
    allowed = True
    if blocks:
        reason = f"risk_hard_block:{blocks[0]}"
        allowed = False
    elif clean_equity <= 0:
        reason = "equity_unavailable"
        allowed = False
    elif daily_loss >= policy.max_daily_loss_percent:
        reason = "daily_loss_limit"
        allowed = False
    elif remaining_slots <= 0:
        reason = "position_limit_reached"
        allowed = False
    elif available_to_allocate < policy.minimum_notional:
        reason = "reserve_or_total_exposure_protected"
        allowed = False
    elif clean_symbol and available_symbol < policy.minimum_notional:
        reason = "symbol_exposure_limit"
        allowed = False
    elif group and available_correlated < policy.minimum_notional:
        reason = "correlated_exposure_limit"
        allowed = False
    elif effective_risk_percent <= 0 or multiplier <= 0:
        reason = "risk_budget_unavailable"
        allowed = False
    elif notional < policy.minimum_notional:
        reason = "allocation_below_minimum"
        allowed = False

    if not allowed:
        notional = 0.0

    utilization_percent = _percent(deployed_notional, clean_equity)
    projected_utilization_percent = _percent(
        deployed_notional + notional,
        clean_equity,
    )
    symbol_exposure_percent = _percent(symbol_notional, clean_equity)
    projected_symbol_exposure_percent = _percent(
        symbol_notional + notional,
        clean_equity,
    )
    correlated_exposure_percent = _percent(correlated_notional, clean_equity)
    projected_correlated_exposure_percent = _percent(
        correlated_notional + notional,
        clean_equity,
    )
    return {
        "status": "ok" if allowed else "blocked",
        "allowed": allowed,
        "reason": reason,
        "notional": notional,
        "symbol": clean_symbol,
        "correlation_group": group,
        "equity": round(clean_equity, 4),
        "reserve_percent": policy.reserve_percent,
        "reserve_amount": reserve_amount,
        "max_total_exposure_percent": policy.max_total_exposure_percent,
        "total_exposure_cap": total_exposure_cap,
        "deployable_capital": deployable_capital,
        "deployed_notional": deployed_notional,
        "available_to_allocate": available_to_allocate,
        "remaining_slots": remaining_slots,
        "equal_slot_budget": equal_slot_budget,
        "position_notional_cap": position_notional_cap,
        "symbol_notional": symbol_notional,
        "symbol_exposure_cap": symbol_exposure_cap,
        "available_symbol_exposure": round(available_symbol, 4),
        "correlated_notional": correlated_notional,
        "correlated_exposure_cap": correlated_exposure_cap,
        "available_correlated_exposure": round(available_correlated, 4),
        "risk_notional_cap": risk_notional_cap,
        "risk_budget": risk_budget,
        "requested_risk_percent": requested_risk,
        "effective_risk_percent": effective_risk_percent,
        "risk_size_multiplier": multiplier,
        "current_daily_loss_percent": daily_loss,
        "hard_blocks": list(blocks),
        "estimated_round_trip_fee_percent": round(round_trip_fee_percent, 6),
        "stop_loss_percent": stop_distance_percent,
        "utilization_percent": utilization_percent,
        "projected_utilization_percent": projected_utilization_percent,
        "symbol_exposure_percent": symbol_exposure_percent,
        "projected_symbol_exposure_percent": projected_symbol_exposure_percent,
        "correlated_exposure_percent": correlated_exposure_percent,
        "projected_correlated_exposure_percent": projected_correlated_exposure_percent,
        "leverage": policy.leverage,
        "policy": policy.snapshot(),
    }


def capital_snapshot(
    *,
    equity: float,
    open_trades: Sequence[Mapping[str, Any]],
    policy: CapitalAllocationPolicy | None = None,
) -> dict[str, Any]:
    """Summarize exposure, reserve, symbols and correlation groups."""

    policy = policy or CapitalAllocationPolicy.from_environment()
    _validate_policy(policy)
    clean_equity = _nonnegative(equity, "equity")
    active = [
        item
        for item in open_trades
        if isinstance(item, Mapping)
        and str(item.get("status", "OPEN")).upper() == "OPEN"
    ]
    deployed = round(sum(_trade_notional(item) for item in active), 4)
    reserve = round(clean_equity * policy.reserve_percent / 100.0, 4)
    total_cap = round(
        clean_equity * policy.max_total_exposure_percent / 100.0,
        4,
    )
    deployable = round(min(max(0.0, clean_equity - reserve), total_cap), 4)
    available = round(max(0.0, deployable - deployed), 4)
    symbols: dict[str, float] = {}
    groups: dict[str, float] = {}
    for item in active:
        notional = _trade_notional(item)
        symbol = _symbol_or_empty(item.get("symbol") or item.get("asset"))
        group = _trade_group(item)
        if symbol:
            symbols[symbol] = round(symbols.get(symbol, 0.0) + notional, 4)
        if group:
            groups[group] = round(groups.get(group, 0.0) + notional, 4)
    return {
        "equity": round(clean_equity, 4),
        "deployed_notional": deployed,
        "reserve_amount": reserve,
        "reserve_percent": policy.reserve_percent,
        "total_exposure_cap": total_cap,
        "deployable_capital": deployable,
        "available_to_allocate": available,
        "capital_utilization_percent": _percent(deployed, clean_equity),
        "deployable_utilization_percent": _percent(deployed, deployable),
        "symbol_exposure_notional": symbols,
        "correlation_exposure_notional": groups,
        "leverage": policy.leverage,
        "policy": policy.snapshot(),
    }


def correlation_group_for_symbol(symbol: Any) -> str:
    """Return a conservative default correlation bucket for common crypto assets."""

    clean = _symbol(symbol)
    if clean in _MAJOR_CRYPTO_SYMBOLS:
        return "crypto_beta"
    return f"symbol:{clean.lower()}"


def _validate_policy(policy: CapitalAllocationPolicy) -> None:
    values = asdict(policy)
    for name, value in values.items():
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"invalid capital policy field: {name}")
    if policy.leverage != 1.0:
        raise ValueError("capital allocation leverage must remain 1.0")
    if policy.reserve_percent + policy.max_total_exposure_percent > 100.000001:
        raise ValueError("reserve plus total exposure exceeds account equity")
    if policy.max_position_percent > policy.max_total_exposure_percent:
        raise ValueError("position cap exceeds total exposure cap")
    if policy.max_symbol_exposure_percent > policy.max_total_exposure_percent:
        raise ValueError("symbol cap exceeds total exposure cap")


def _trade_notional(item: Mapping[str, Any]) -> float:
    value = item.get("notional")
    if value in (None, ""):
        quantity = item.get("quantity", 0.0)
        price = item.get("current_price", item.get("entry_price", item.get("price", 0.0)))
        try:
            value = float(quantity) * float(price)
        except (TypeError, ValueError):
            value = 0.0
    return max(0.0, _finite(value, "trade notional"))


def _trade_group(item: Mapping[str, Any]) -> str:
    explicit = str(
        item.get("correlation_group")
        or item.get("capital_allocation", {}).get("correlation_group", "")
        if isinstance(item.get("capital_allocation"), Mapping)
        else item.get("correlation_group", "")
    ).strip().lower()
    if explicit:
        return explicit
    symbol = item.get("symbol") or item.get("asset")
    return correlation_group_for_symbol(symbol) if symbol else ""


def _symbol_or_empty(value: Any) -> str:
    try:
        return _symbol(value)
    except ValueError:
        return ""


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("invalid symbol")
    return clean


def _nonnegative(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _bounded_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    parsed = _finite(value, name)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bounded_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return round(min(max(value, minimum), maximum), 6)


def _percent(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100.0, 4) if denominator > 0 else 0.0


__all__ = [
    "CapitalAllocationPolicy",
    "build_capital_allocation",
    "capital_snapshot",
    "correlation_group_for_symbol",
]
