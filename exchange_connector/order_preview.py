"""Pure, non-executing order preview calculations for SharipovAI.

This module never sends exchange requests. It validates order intent, rounds price
and quantity to exchange rules, estimates fees/slippage, and calculates loss at
stop and reward at take profit. Invalid or unsafe inputs fail closed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Any


class OrderPreviewError(ValueError):
    """Raised when an order cannot be previewed safely."""


@dataclass(frozen=True, slots=True)
class InstrumentRules:
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal


@dataclass(frozen=True, slots=True)
class OrderPreview:
    symbol: str
    side: str
    order_type: str
    quantity: float
    entry_price: float
    notional: float
    estimated_entry_fee: float
    estimated_exit_fee: float
    estimated_slippage: float
    stop_loss: float
    take_profit: float
    maximum_loss: float
    potential_reward: float
    risk_reward_ratio: float
    risk_percent_of_equity: float
    leverage: float
    margin_required: float
    executable: bool = False
    sends_order: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_order_preview(payload: dict[str, Any]) -> OrderPreview:
    symbol = str(payload.get("symbol", "")).strip().upper().replace("/", "").replace("-", "")
    side = str(payload.get("side", "")).strip().lower()
    order_type = str(payload.get("order_type", "limit")).strip().lower()
    if not symbol or not symbol.isalnum():
        raise OrderPreviewError("symbol is invalid")
    if side not in {"buy", "sell"}:
        raise OrderPreviewError("side must be buy or sell")
    if order_type not in {"market", "limit"}:
        raise OrderPreviewError("order_type must be market or limit")

    equity = _positive(payload.get("account_equity"), "account_equity")
    requested_qty = _positive(payload.get("quantity"), "quantity")
    reference_price = _positive(payload.get("reference_price"), "reference_price")
    stop = _positive(payload.get("stop_loss"), "stop_loss")
    take = _positive(payload.get("take_profit"), "take_profit")
    leverage = _positive(payload.get("leverage", 1), "leverage")
    if leverage > Decimal("100"):
        raise OrderPreviewError("leverage exceeds hard preview limit")

    rules = InstrumentRules(
        tick_size=_positive(payload.get("tick_size"), "tick_size"),
        qty_step=_positive(payload.get("qty_step"), "qty_step"),
        min_qty=_positive(payload.get("min_qty"), "min_qty"),
        min_notional=_positive(payload.get("min_notional"), "min_notional"),
    )
    fee_rate = _nonnegative(payload.get("fee_rate", "0.001"), "fee_rate")
    slippage_rate = _nonnegative(payload.get("slippage_percent", "0"), "slippage_percent") / Decimal("100")

    qty = _round_step(requested_qty, rules.qty_step, ROUND_DOWN)
    if qty < rules.min_qty:
        raise OrderPreviewError("quantity is below minimum")

    if order_type == "market":
        direction = Decimal("1") if side == "buy" else Decimal("-1")
        entry = reference_price * (Decimal("1") + direction * slippage_rate)
    else:
        entry = _positive(payload.get("limit_price"), "limit_price")
    entry = _round_step(entry, rules.tick_size, ROUND_UP if side == "buy" else ROUND_DOWN)
    stop = _round_step(stop, rules.tick_size, ROUND_DOWN if side == "buy" else ROUND_UP)
    take = _round_step(take, rules.tick_size, ROUND_UP if side == "buy" else ROUND_DOWN)

    if side == "buy" and not (stop < entry < take):
        raise OrderPreviewError("buy preview requires stop_loss < entry_price < take_profit")
    if side == "sell" and not (take < entry < stop):
        raise OrderPreviewError("sell preview requires take_profit < entry_price < stop_loss")

    notional = qty * entry
    if notional < rules.min_notional:
        raise OrderPreviewError("order notional is below minimum")

    entry_fee = notional * fee_rate
    exit_reference = stop
    exit_fee = qty * exit_reference * fee_rate
    slippage_cost = qty * reference_price * slippage_rate
    price_risk = qty * abs(entry - stop)
    reward = qty * abs(take - entry)
    maximum_loss = price_risk + entry_fee + exit_fee + slippage_cost
    if maximum_loss <= 0:
        raise OrderPreviewError("maximum loss must be positive")
    risk_percent = maximum_loss / equity * Decimal("100")
    max_risk_percent = _positive(payload.get("max_risk_percent", "1"), "max_risk_percent")
    if risk_percent > max_risk_percent:
        raise OrderPreviewError("preview exceeds maximum risk percent")

    margin = notional / leverage
    ratio = reward / maximum_loss
    return OrderPreview(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=float(qty),
        entry_price=float(entry),
        notional=float(notional),
        estimated_entry_fee=float(entry_fee),
        estimated_exit_fee=float(exit_fee),
        estimated_slippage=float(slippage_cost),
        stop_loss=float(stop),
        take_profit=float(take),
        maximum_loss=float(maximum_loss),
        potential_reward=float(reward),
        risk_reward_ratio=float(ratio),
        risk_percent_of_equity=float(risk_percent),
        leverage=float(leverage),
        margin_required=float(margin),
    )


def _positive(value: Any, name: str) -> Decimal:
    result = _decimal(value, name)
    if result <= 0:
        raise OrderPreviewError(f"{name} must be greater than zero")
    return result


def _nonnegative(value: Any, name: str) -> Decimal:
    result = _decimal(value, name)
    if result < 0:
        raise OrderPreviewError(f"{name} must not be negative")
    return result


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OrderPreviewError(f"{name} is invalid") from exc
    if not result.is_finite():
        raise OrderPreviewError(f"{name} must be finite")
    return result


def _round_step(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    units = (value / step).to_integral_value(rounding=rounding)
    return units * step
