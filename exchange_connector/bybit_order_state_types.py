"""Validated types and transitions for private Bybit order state."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any

OPEN_STATUSES = {"Untriggered", "New", "PartiallyFilled"}
INSTANTANEOUS_CLOSED_STATUSES = {"Triggered"}
TERMINAL_STATUSES = {"Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}
CLOSED_STATUSES = INSTANTANEOUS_CLOSED_STATUSES | TERMINAL_STATUSES
ALLOWED_STATUSES = OPEN_STATUSES | CLOSED_STATUSES
TRANSITIONS = {
    "Untriggered": {"Untriggered", "Triggered", "New", "Cancelled", "Rejected", "Deactivated"},
    "Triggered": {"Triggered", "New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "Deactivated"},
    "New": {"New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled", "PartiallyFilledCanceled"},
}
CATEGORIES = {"spot", "linear", "inverse", "option"}
SIDES = {"Buy", "Sell"}
TOPICS = {"order", "order.spot", "order.linear", "order.inverse", "order.option"}
ENVIRONMENTS = {"testnet", "mainnet"}
MANAGED_ORDER_LINK_PREFIX = "sai_"
TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class OrderState:
    environment: str
    order_id: str
    order_link_id: str
    category: str
    symbol: str
    side: str
    status: str
    qty: float
    cum_exec_qty: float
    avg_price: float
    created_time_ms: int
    updated_time_ms: int
    message_creation_time_ms: int
    message_id: str
    reject_reason: str = ""

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_order_event(
    row: Any,
    *,
    topic: str,
    environment: str,
    message_id: str,
    message_creation_ms: int,
    received_at_ms: int,
    max_message_lag_ms: int,
    future_skew_ms: int,
) -> OrderState:
    if not isinstance(row, Mapping):
        raise TypeError("order event must be an object")
    order_id = optional_identifier(row.get("orderId"), "orderId")
    link_id = optional_order_link_id(row.get("orderLinkId"))
    if not order_id and not link_id:
        raise ValueError("orderId or orderLinkId is required")
    category = str(row.get("category", "")).strip().lower()
    if category not in CATEGORIES:
        raise ValueError("invalid category")
    if "." in topic and topic.split(".", 1)[1] != category:
        raise ValueError("topic and category mismatch")
    symbol = str(row.get("symbol", "")).strip().upper()
    validate_symbol(symbol)
    side = str(row.get("side", "")).strip().title()
    if side not in SIDES:
        raise ValueError("invalid side")
    status = str(row.get("orderStatus", "")).strip()
    if status not in ALLOWED_STATUSES:
        raise ValueError("invalid orderStatus")
    qty = number(row.get("qty"), "qty", positive=True)
    executed = number(row.get("cumExecQty", 0), "cumExecQty")
    if executed > qty + TOLERANCE:
        raise ValueError("cumExecQty exceeds qty")
    average = number(row.get("avgPrice") or 0, "avgPrice")
    created = positive_int(row.get("createdTime"), "createdTime")
    updated = positive_int(row.get("updatedTime"), "updatedTime")
    if updated < created:
        raise ValueError("updatedTime precedes createdTime")
    if updated > received_at_ms + future_skew_ms or created > received_at_ms + future_skew_ms:
        raise ValueError("order timestamp is in the future")
    if updated > message_creation_ms + future_skew_ms:
        raise ValueError("updatedTime is ahead of message creationTime")
    if received_at_ms - updated > max_message_lag_ms:
        raise ValueError("order event row is too old or replayed")
    state = OrderState(
        environment=environment,
        order_id=order_id,
        order_link_id=link_id,
        category=category,
        symbol=symbol,
        side=side,
        status=status,
        qty=qty,
        cum_exec_qty=executed,
        avg_price=average,
        created_time_ms=created,
        updated_time_ms=updated,
        message_creation_time_ms=message_creation_ms,
        message_id=message_id,
        reject_reason=str(row.get("rejectReason", "")).strip(),
    )
    validate_state_semantics(state)
    return state


def resolve_canonical(aliases: Mapping[str, str], order_id: str, link_id: str) -> str | None:
    candidates = set()
    if order_id and aliases.get(f"order:{order_id}"):
        candidates.add(aliases[f"order:{order_id}"])
    if link_id and aliases.get(f"link:{link_id}"):
        candidates.add(aliases[f"link:{link_id}"])
    if len(candidates) > 1:
        raise RuntimeError("orderId and orderLinkId resolve to different orders")
    return next(iter(candidates), None)


def bind_aliases(aliases: dict[str, str], canonical: str, order_id: str, link_id: str) -> None:
    alias_values = ([f"order:{order_id}"] if order_id else []) + ([f"link:{link_id}"] if link_id else [])
    for alias in alias_values:
        existing = aliases.get(alias)
        if existing and existing != canonical:
            raise RuntimeError("order alias collision")
        aliases[alias] = canonical


def merge_order_state(existing_raw: Any, new: OrderState) -> tuple[str, OrderState]:
    if existing_raw is None:
        return "accepted", new
    if not isinstance(existing_raw, Mapping):
        raise RuntimeError("persisted order state is invalid")
    existing = state_from_mapping(existing_raw)
    immutable = ("environment", "category", "symbol", "side", "qty", "created_time_ms")
    for field in immutable:
        old_value = getattr(existing, field)
        new_value = getattr(new, field)
        if isinstance(old_value, float):
            if abs(old_value - new_value) > TOLERANCE:
                raise ValueError(f"immutable field changed: {field}")
        elif old_value != new_value:
            raise ValueError(f"immutable field changed: {field}")
    if existing.order_id and new.order_id and existing.order_id != new.order_id:
        raise ValueError("orderId changed")
    if existing.order_link_id and new.order_link_id and existing.order_link_id != new.order_link_id:
        raise ValueError("orderLinkId changed")
    if new.updated_time_ms < existing.updated_time_ms:
        raise ValueError("out-of-order updatedTime")
    if new.cum_exec_qty < existing.cum_exec_qty - TOLERANCE:
        raise ValueError("cumExecQty regression")

    merged = replace(
        new,
        order_id=new.order_id or existing.order_id,
        order_link_id=new.order_link_id or existing.order_link_id,
    )
    same_execution = (
        merged.status == existing.status
        and abs(merged.cum_exec_qty - existing.cum_exec_qty) <= TOLERANCE
        and abs(merged.avg_price - existing.avg_price) <= TOLERANCE
    )
    identity_enriched = (
        (not existing.order_id and bool(merged.order_id))
        or (not existing.order_link_id and bool(merged.order_link_id))
    )

    if existing.terminal:
        if not same_execution:
            raise ValueError("terminal order cannot change")
        return ("accepted", merged) if identity_enriched else ("duplicate", existing)
    if merged.updated_time_ms == existing.updated_time_ms:
        if same_execution and identity_enriched:
            return "accepted", merged
        if same_execution:
            return "duplicate", existing
        raise ValueError("conflicting state at identical updatedTime")
    if merged.status not in TRANSITIONS.get(existing.status, {existing.status}):
        raise ValueError(f"invalid transition {existing.status}->{merged.status}")
    return "accepted", merged


def validate_document(data: Any, *, environment: str) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("orders"), dict) or not isinstance(data.get("aliases"), dict):
        raise RuntimeError("order state file has invalid structure")
    if data.get("updated_at_ms") is not None:
        positive_int(data.get("updated_at_ms"), "persisted updated_at_ms")
    expected_aliases: dict[str, str] = {}
    for canonical, raw in data["orders"].items():
        if not isinstance(canonical, str) or not canonical.startswith(("order:", "link:")):
            raise RuntimeError("order state contains an invalid canonical key")
        if not isinstance(raw, dict):
            raise RuntimeError("order state contains an invalid record")
        try:
            state = state_from_mapping(raw)
            if state.environment != environment:
                raise ValueError("persisted order environment mismatch")
            validate_persisted_state(state, canonical=canonical)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"persisted order state is inconsistent: {exc}") from exc
        alias_values = ([f"order:{state.order_id}"] if state.order_id else []) + (
            [f"link:{state.order_link_id}"] if state.order_link_id else []
        )
        for alias in alias_values:
            existing = expected_aliases.get(alias)
            if existing and existing != canonical:
                raise RuntimeError("persisted order aliases collide")
            expected_aliases[alias] = canonical
    aliases = data["aliases"]
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in aliases.items()):
        raise RuntimeError("order state aliases are invalid")
    if aliases != expected_aliases:
        raise RuntimeError("order state aliases do not match order records")


def state_from_mapping(raw: Mapping[str, Any]) -> OrderState:
    try:
        return OrderState(**dict(raw))
    except TypeError as exc:
        raise RuntimeError("persisted order state is invalid") from exc


def validate_persisted_state(state: OrderState, *, canonical: str) -> None:
    order_id = optional_identifier(state.order_id, "persisted orderId")
    link_id = optional_order_link_id(state.order_link_id)
    if not order_id and not link_id:
        raise ValueError("persisted order has no identity")
    valid_keys = ({f"order:{order_id}"} if order_id else set()) | ({f"link:{link_id}"} if link_id else set())
    if canonical not in valid_keys:
        raise ValueError("canonical key does not match persisted identifiers")
    if state.category not in CATEGORIES:
        raise ValueError("invalid category")
    validate_symbol(state.symbol)
    if state.symbol != state.symbol.upper():
        raise ValueError("symbol must be uppercase")
    if state.side not in SIDES:
        raise ValueError("invalid side")
    if state.status not in ALLOWED_STATUSES:
        raise ValueError("invalid order status")
    number(state.qty, "persisted qty", positive=True)
    number(state.cum_exec_qty, "persisted cum_exec_qty")
    number(state.avg_price, "persisted avg_price")
    created = positive_int(state.created_time_ms, "persisted created_time_ms")
    updated = positive_int(state.updated_time_ms, "persisted updated_time_ms")
    message_time = positive_int(state.message_creation_time_ms, "persisted message_creation_time_ms")
    if updated < created:
        raise ValueError("updated_time_ms precedes created_time_ms")
    if updated > message_time + 5_000:
        raise ValueError("updated_time_ms is ahead of message_creation_time_ms")
    optional_identifier(state.message_id, "persisted message_id")
    validate_state_semantics(state)


def validate_state_semantics(state: OrderState) -> None:
    executed = state.cum_exec_qty
    qty = state.qty
    average = state.avg_price
    if executed > TOLERANCE and average <= 0:
        raise ValueError("avgPrice must be positive after execution")
    if executed <= TOLERANCE and average > TOLERANCE:
        raise ValueError("avgPrice must be zero before execution")
    if state.status == "Filled" and abs(executed - qty) > TOLERANCE:
        raise ValueError("Filled requires cumExecQty equal to qty")
    if state.status in {"PartiallyFilled", "PartiallyFilledCanceled"} and not (
        TOLERANCE < executed < qty - TOLERANCE
    ):
        raise ValueError(f"{state.status} requires a partial executed quantity")
    if state.status == "PartiallyFilledCanceled" and state.category != "spot":
        raise ValueError("PartiallyFilledCanceled is valid only for spot orders")
    if state.status == "Cancelled" and executed >= qty - TOLERANCE:
        raise ValueError("Cancelled cannot report a fully executed quantity")
    if state.status == "Cancelled" and state.category == "spot" and executed > TOLERANCE:
        raise ValueError("partially filled spot cancellation requires PartiallyFilledCanceled")
    if state.status in {"Untriggered", "Triggered", "New", "Rejected", "Deactivated"} and executed > TOLERANCE:
        raise ValueError(f"{state.status} cannot report executed quantity")


def environment(value: str) -> str:
    clean = str(value).strip().lower()
    if clean in {"sandbox", "testnet"}:
        clean = "testnet"
    elif clean in {"live", "mainnet"}:
        clean = "mainnet"
    if clean not in ENVIRONMENTS:
        raise ValueError("environment must be testnet or mainnet")
    return clean


def optional_identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 128 or not all(char.isalnum() or char in "._:-" for char in text):
        raise ValueError(f"{name} has invalid format")
    return text


def optional_order_link_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 36 or not all(char.isalnum() or char in "_-" for char in text):
        raise ValueError("orderLinkId has invalid format")
    return text


def validate_symbol(symbol: str) -> None:
    if not symbol or len(symbol) > 80 or not all(char.isalnum() or char in "-_" for char in symbol):
        raise ValueError("invalid symbol")


def positive_int(value: Any, name: str) -> int:
    parsed = integer(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc


def finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def number(value: Any, name: str, *, positive: bool = False) -> float:
    parsed = finite_float(value, name)
    if parsed < 0 or (positive and parsed <= 0):
        raise ValueError(f"{name} is outside the allowed range")
    return parsed
