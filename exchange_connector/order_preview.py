"""Conservative non-executing order preview based on verified exchange rules."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Any

from .bybit_instrument_rules import BybitInstrumentRules


class OrderPreviewError(ValueError):
    """Raised when an order intent cannot be previewed safely."""


_FORBIDDEN_RULE_FIELDS = {
    "tick_size",
    "qty_step",
    "min_qty",
    "min_notional",
    "max_qty",
    "min_price",
    "max_price",
    "min_leverage",
    "max_leverage",
}


@dataclass(frozen=True, slots=True)
class OrderPreview:
    symbol: str
    category: str
    side: str
    order_type: str
    quantity: float
    reference_price: float
    entry_price: float
    notional: float
    estimated_entry_fee: float
    estimated_exit_fee_at_stop: float
    estimated_slippage: float
    stop_loss: float
    take_profit: float
    maximum_loss: float
    potential_reward: float
    risk_reward_ratio: float
    risk_percent_of_equity: float
    max_risk_percent: float
    leverage: float
    required_capital: float
    available_balance: float
    instrument_rules_fetched_at_ms: int
    risk_approved: bool = False
    executable: bool = False
    executed: bool = False
    sends_order: bool = False
    funding_included: bool = False
    liquidation_checked: bool = False
    correlation_checked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_order_preview(payload: dict[str, Any], rules: BybitInstrumentRules) -> OrderPreview:
    if not isinstance(payload, dict):
        raise OrderPreviewError("payload must be an object")
    forbidden = sorted(_FORBIDDEN_RULE_FIELDS.intersection(payload))
    if forbidden:
        raise OrderPreviewError(f"instrument rules cannot be supplied manually: {', '.join(forbidden)}")

    symbol = _symbol(payload.get("symbol"))
    category = str(payload.get("category", "spot")).strip().lower()
    side = str(payload.get("side", "")).strip().lower()
    order_type = str(payload.get("order_type", "limit")).strip().lower()
    if symbol != rules.symbol or category != rules.category:
        raise OrderPreviewError("verified instrument rules do not match the requested order")
    if category not in {"spot", "linear"}:
        raise OrderPreviewError("preview currently supports spot and linear only")
    if side not in {"buy", "sell"}:
        raise OrderPreviewError("side must be buy or sell")
    if order_type not in {"market", "limit"}:
        raise OrderPreviewError("order_type must be market or limit")

    equity = _positive(payload.get("account_equity"), "account_equity")
    available_balance = _nonnegative(payload.get("available_balance"), "available_balance")
    requested_qty = _positive(payload.get("quantity"), "quantity")
    reference_price = _positive(payload.get("reference_price"), "reference_price")
    stop = _positive(payload.get("stop_loss"), "stop_loss")
    take = _positive(payload.get("take_profit"), "take_profit")
    fee_rate = _bounded_nonnegative(payload.get("fee_rate", "0.001"), "fee_rate", Decimal("0.05"))
    exit_fee_rate = _bounded_nonnegative(
        payload.get("exit_fee_rate", fee_rate), "exit_fee_rate", Decimal("0.05")
    )
    slippage_percent = _bounded_nonnegative(
        payload.get("slippage_percent", "0.1" if order_type == "market" else "0"),
        "slippage_percent",
        Decimal("5"),
    )
    if order_type == "limit" and slippage_percent != 0:
        raise OrderPreviewError("limit preview requires slippage_percent=0")

    max_risk_percent = _positive(payload.get("max_risk_percent"), "max_risk_percent")
    if max_risk_percent > Decimal("5"):
        raise OrderPreviewError("max_risk_percent exceeds hard preview limit of 5%")

    qty = _round_step(requested_qty, rules.qty_step, ROUND_DOWN)
    if qty < rules.min_qty:
        raise OrderPreviewError("quantity is below verified minimum")
    maximum_qty = rules.max_market_qty if order_type == "market" else rules.max_limit_qty
    if maximum_qty is not None and qty > maximum_qty:
        raise OrderPreviewError("quantity exceeds verified order-type maximum")

    leverage = _positive(payload.get("leverage", "1"), "leverage")
    if category == "spot":
        if leverage != 1:
            raise OrderPreviewError("spot preview requires leverage=1")
    else:
        if rules.min_leverage is None or rules.max_leverage is None or rules.leverage_step is None:
            raise OrderPreviewError("verified leverage rules are unavailable")
        if not rules.min_leverage <= leverage <= rules.max_leverage:
            raise OrderPreviewError("leverage is outside verified limits")
        if not _is_step_aligned(leverage - rules.min_leverage, rules.leverage_step):
            raise OrderPreviewError("leverage is not aligned to verified leverageStep")

    if order_type == "market":
        slippage_rate = slippage_percent / Decimal("100")
        adjusted = reference_price * (
            Decimal("1") + slippage_rate if side == "buy" else Decimal("1") - slippage_rate
        )
        entry = _round_step(adjusted, rules.tick_size, ROUND_UP if side == "buy" else ROUND_DOWN)
    else:
        requested_limit = _positive(payload.get("limit_price"), "limit_price")
        entry = _round_step(
            requested_limit,
            rules.tick_size,
            ROUND_DOWN if side == "buy" else ROUND_UP,
        )

    # Conservative rounding: never overstate reward or understate stop distance.
    stop = _round_step(stop, rules.tick_size, ROUND_DOWN if side == "buy" else ROUND_UP)
    take = _round_step(take, rules.tick_size, ROUND_DOWN if side == "buy" else ROUND_UP)
    for name, value in (("entry_price", entry), ("stop_loss", stop), ("take_profit", take)):
        _check_price_bounds(value, name, rules)

    if side == "buy" and not (stop < entry < take):
        raise OrderPreviewError("buy preview requires stop_loss < entry_price < take_profit")
    if side == "sell" and not (take < entry < stop):
        raise OrderPreviewError("sell preview requires take_profit < entry_price < stop_loss")

    notional = qty * entry
    if notional < rules.min_notional:
        raise OrderPreviewError("order notional is below verified minimum")

    entry_fee = notional * fee_rate
    stop_exit_fee = qty * stop * exit_fee_rate
    take_exit_fee = qty * take * exit_fee_rate
    slippage_cost = qty * abs(entry - reference_price) if order_type == "market" else Decimal("0")
    # Entry already includes the adverse slippage adjustment, so slippage_cost is
    # reported but is not added a second time to maximum_loss.
    price_risk = qty * abs(entry - stop)
    maximum_loss = price_risk + entry_fee + stop_exit_fee
    gross_reward = qty * abs(take - entry)
    potential_reward = gross_reward - entry_fee - take_exit_fee
    if maximum_loss <= 0 or potential_reward <= 0:
        raise OrderPreviewError("fees and price levels produce no positive risk/reward preview")

    risk_percent = maximum_loss / equity * Decimal("100")
    if risk_percent > max_risk_percent:
        raise OrderPreviewError("preview exceeds maximum risk percent")

    if category == "linear":
        required_capital = notional / leverage + entry_fee
        if required_capital > available_balance:
            raise OrderPreviewError("required margin and fee exceed available balance")
    elif side == "buy":
        required_capital = notional + entry_fee
        if required_capital > available_balance:
            raise OrderPreviewError("spot purchase cost and fee exceed available balance")
    else:
        available_asset = _nonnegative(
            payload.get("available_asset_quantity"), "available_asset_quantity"
        )
        if qty > available_asset:
            raise OrderPreviewError("spot sale quantity exceeds available asset quantity")
        required_capital = Decimal("0")

    return OrderPreview(
        symbol=symbol,
        category=category,
        side=side,
        order_type=order_type,
        quantity=float(qty),
        reference_price=float(reference_price),
        entry_price=float(entry),
        notional=float(notional),
        estimated_entry_fee=float(entry_fee),
        estimated_exit_fee_at_stop=float(stop_exit_fee),
        estimated_slippage=float(slippage_cost),
        stop_loss=float(stop),
        take_profit=float(take),
        maximum_loss=float(maximum_loss),
        potential_reward=float(potential_reward),
        risk_reward_ratio=float(potential_reward / maximum_loss),
        risk_percent_of_equity=float(risk_percent),
        max_risk_percent=float(max_risk_percent),
        leverage=float(leverage),
        required_capital=float(required_capital),
        available_balance=float(available_balance),
        instrument_rules_fetched_at_ms=rules.fetched_at_ms,
    )


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise OrderPreviewError("symbol is invalid")
    return clean


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise OrderPreviewError(f"{name} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OrderPreviewError(f"{name} is invalid") from exc
    if not result.is_finite():
        raise OrderPreviewError(f"{name} must be finite")
    return result


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


def _bounded_nonnegative(value: Any, name: str, upper: Decimal) -> Decimal:
    result = _nonnegative(value, name)
    if result > upper:
        raise OrderPreviewError(f"{name} exceeds hard preview limit")
    return result


def _round_step(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    units = (value / step).to_integral_value(rounding=rounding)
    return units * step


def _is_step_aligned(value: Decimal, step: Decimal) -> bool:
    return value >= 0 and value % step == 0


def _check_price_bounds(value: Decimal, name: str, rules: BybitInstrumentRules) -> None:
    if rules.min_price is not None and value < rules.min_price:
        raise OrderPreviewError(f"{name} is below verified minimum price")
    if rules.max_price is not None and value > rules.max_price:
        raise OrderPreviewError(f"{name} exceeds verified maximum price")
