"""Fail-closed state tracker for Bybit private order WebSocket events.

This module does not open sockets and does not place, amend, or cancel orders. It
validates order events, rejects regressions/out-of-order transitions, persists the
latest state atomically, and reconciles accepted journal entries after restart.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any

_ALLOWED_TOPICS = {"order", "order.spot", "order.linear", "order.inverse", "order.option"}
_ALLOWED_CATEGORIES = {"spot", "linear", "inverse", "option"}
_ALLOWED_SIDES = {"Buy", "Sell"}
_OPEN_STATUSES = {"New", "PartiallyFilled", "Untriggered", "Triggered"}
_TERMINAL_STATUSES = {"Rejected", "PartiallyFilledCanceled", "Filled", "Cancelled", "Deactivated"}
_ALLOWED_STATUSES = _OPEN_STATUSES | _TERMINAL_STATUSES
_TRANSITIONS = {
    "Untriggered": {"Untriggered", "Triggered", "New", "Cancelled", "Rejected", "Deactivated"},
    "Triggered": {"Triggered", "New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "Deactivated"},
    "New": {"New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled", "PartiallyFilledCanceled"},
}


@dataclass(frozen=True, slots=True)
class OrderState:
    order_id: str
    order_link_id: str
    category: str
    symbol: str
    side: str
    status: str
    qty: float
    cum_exec_qty: float
    avg_price: float
    reject_reason: str
    created_time_ms: int
    updated_time_ms: int
    last_message_id: str
    last_creation_time_ms: int

    @property
    def key(self) -> str:
        return self.order_id or f"link:{self.order_link_id}"

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitOrderStateStore:
    """Persist and validate the latest known state for each Bybit order."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("BYBIT_ORDER_STATE_FILE", "data/bybit_order_state.json"))
        self._lock = threading.RLock()

    def ingest_message(self, message: Mapping[str, Any], *, received_at_ms: int | None = None) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("message must be an object")
        topic = str(message.get("topic", "")).strip()
        if topic not in _ALLOWED_TOPICS:
            raise ValueError("unsupported Bybit order topic")
        message_id = str(message.get("id", "")).strip()
        creation_time = _positive_int(message.get("creationTime"), "creationTime")
        current_ms = int(time.time() * 1000) if received_at_ms is None else _positive_int(received_at_ms, "received_at_ms")
        if creation_time > current_ms + 1_000:
            raise ValueError("creationTime is too far in the future")
        data = message.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError("data must be a non-empty list")

        with self._lock:
            document = self._load_document()
            orders = dict(document.get("orders", {}))
            accepted: list[str] = []
            duplicates: list[str] = []
            rejected: list[dict[str, str]] = []

            for index, raw in enumerate(data):
                try:
                    state = _normalize_order(raw, message_id=message_id, creation_time=creation_time)
                    outcome = _apply_state(orders.get(state.key), state)
                    if outcome == "duplicate":
                        duplicates.append(state.key)
                    else:
                        orders[state.key] = state.to_dict()
                        accepted.append(state.key)
                except (TypeError, ValueError) as exc:
                    rejected.append({"index": str(index), "reason": str(exc)})

            if accepted:
                self._write_document({"orders": orders, "updated_at_ms": current_ms})

        status = "ok" if not rejected else "partial" if accepted or duplicates else "blocked"
        return {
            "status": status,
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
            "tracked_orders": len(orders),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            document = self._load_document()
        orders = document.get("orders", {})
        values = [dict(value) for value in orders.values() if isinstance(value, Mapping)]
        return {
            "status": "ok",
            "updated_at_ms": document.get("updated_at_ms"),
            "tracked_orders": len(values),
            "open_orders": [item for item in values if item.get("status") in _OPEN_STATUSES],
            "terminal_orders": [item for item in values if item.get("status") in _TERMINAL_STATUSES],
            "orders": values,
        }

    def _load_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": {}, "updated_at_ms": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"order state file is unreadable: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("orders", {}), dict):
            raise RuntimeError("order state file has invalid structure")
        return data

    def _write_document(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


def reconcile_execution_journal(
    journal: Mapping[str, Any],
    tracker_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare accepted execution records with tracked private order states."""
    journal_orders = journal.get("orders", []) if isinstance(journal, Mapping) else []
    tracked_orders = tracker_snapshot.get("orders", []) if isinstance(tracker_snapshot, Mapping) else []
    if not isinstance(journal_orders, list) or not isinstance(tracked_orders, list):
        raise TypeError("journal and tracker snapshot must contain order lists")

    by_order_id: dict[str, Mapping[str, Any]] = {}
    by_link_id: dict[str, Mapping[str, Any]] = {}
    for item in tracked_orders:
        if not isinstance(item, Mapping):
            continue
        order_id = str(item.get("order_id", "")).strip()
        link_id = str(item.get("order_link_id", "")).strip()
        if order_id:
            by_order_id[order_id] = item
        if link_id:
            by_link_id[link_id] = item

    accepted_entries = [item for item in journal_orders if isinstance(item, Mapping) and item.get("status") == "accepted"]
    missing_identifier: list[int] = []
    unresolved: list[dict[str, str]] = []
    matched_open: list[str] = []
    matched_terminal: list[str] = []

    for index, item in enumerate(accepted_entries):
        order_id = str(item.get("order_id", "")).strip()
        link_id = str(item.get("order_link_id", "")).strip()
        if not order_id and not link_id:
            missing_identifier.append(index)
            continue
        tracked = by_order_id.get(order_id) if order_id else None
        if tracked is None and link_id:
            tracked = by_link_id.get(link_id)
        identity = order_id or link_id
        if tracked is None:
            unresolved.append({"identity": identity, "reason": "no private order state observed"})
            continue
        status = str(tracked.get("status", ""))
        if status in _TERMINAL_STATUSES:
            matched_terminal.append(identity)
        else:
            matched_open.append(identity)

    status = "ok" if not missing_identifier and not unresolved else "warning"
    return {
        "status": status,
        "accepted_journal_orders": len(accepted_entries),
        "matched_open": matched_open,
        "matched_terminal": matched_terminal,
        "unresolved": unresolved,
        "missing_identifier_indexes": missing_identifier,
        "restart_safe": status == "ok",
    }


def _normalize_order(raw: Any, *, message_id: str, creation_time: int) -> OrderState:
    if not isinstance(raw, Mapping):
        raise TypeError("order event must be an object")
    order_id = str(raw.get("orderId", "")).strip()
    order_link_id = str(raw.get("orderLinkId", "")).strip()
    if not order_id and not order_link_id:
        raise ValueError("orderId or orderLinkId is required")
    category = str(raw.get("category", "")).strip().lower()
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError("invalid category")
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not symbol or len(symbol) > 80 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in symbol):
        raise ValueError("invalid symbol")
    side = str(raw.get("side", "")).strip().title()
    if side not in _ALLOWED_SIDES:
        raise ValueError("invalid side")
    status = str(raw.get("orderStatus", "")).strip()
    if status not in _ALLOWED_STATUSES:
        raise ValueError("invalid orderStatus")
    qty = _number(raw.get("qty"), "qty", minimum=0.0, strict=True)
    cum_exec_qty = _number(raw.get("cumExecQty", 0), "cumExecQty", minimum=0.0)
    if cum_exec_qty > qty + 1e-12:
        raise ValueError("cumExecQty exceeds qty")
    avg_price = _number(raw.get("avgPrice", 0), "avgPrice", minimum=0.0, empty_zero=True)
    created_time = _positive_int(raw.get("createdTime"), "createdTime")
    updated_time = _positive_int(raw.get("updatedTime"), "updatedTime")
    if updated_time < created_time:
        raise ValueError("updatedTime must not be earlier than createdTime")
    return OrderState(
        order_id=order_id,
        order_link_id=order_link_id,
        category=category,
        symbol=symbol,
        side=side,
        status=status,
        qty=qty,
        cum_exec_qty=cum_exec_qty,
        avg_price=avg_price,
        reject_reason=str(raw.get("rejectReason", "")).strip(),
        created_time_ms=created_time,
        updated_time_ms=updated_time,
        last_message_id=message_id,
        last_creation_time_ms=creation_time,
    )


def _apply_state(existing_raw: Any, new: OrderState) -> str:
    if existing_raw is None:
        return "accepted"
    if not isinstance(existing_raw, Mapping):
        raise ValueError("persisted order state is invalid")
    existing = OrderState(**dict(existing_raw))
    if new.updated_time_ms < existing.updated_time_ms:
        raise ValueError("out-of-order updatedTime")
    if new.cum_exec_qty < existing.cum_exec_qty - 1e-12:
        raise ValueError("cumExecQty regression")
    same_business_state = (
        new.status == existing.status
        and abs(new.cum_exec_qty - existing.cum_exec_qty) <= 1e-12
        and abs(new.avg_price - existing.avg_price) <= 1e-12
    )
    if same_business_state:
        return "duplicate"
    if new.updated_time_ms == existing.updated_time_ms:
        raise ValueError("conflicting event with identical updatedTime")
    if existing.terminal:
        raise ValueError("terminal order cannot transition to another state")
    allowed = _TRANSITIONS.get(existing.status, {existing.status})
    if new.status not in allowed:
        raise ValueError(f"invalid transition {existing.status}->{new.status}")
    return "accepted"


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _number(
    value: Any,
    name: str,
    *,
    minimum: float,
    strict: bool = False,
    empty_zero: bool = False,
) -> float:
    if empty_zero and value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a number") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    if parsed < minimum or (strict and parsed <= minimum):
        comparator = "greater than" if strict else "at least"
        raise ValueError(f"{name} must be {comparator} {minimum}")
    return parsed
