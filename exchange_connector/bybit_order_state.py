"""Fail-closed state tracker for Bybit private order WebSocket events.

This module does not open sockets and does not place, amend, or cancel orders. It
validates event freshness and identity, persists the latest state atomically, and
reconciles execution evidence before restart.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

_ALLOWED_TOPICS = {"order", "order.spot", "order.linear", "order.inverse", "order.option"}
_ALLOWED_CATEGORIES = {"spot", "linear", "inverse", "option"}
_ALLOWED_ENVIRONMENTS = {"paper", "testnet", "mainnet"}
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
    environment: str
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
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitOrderStateStore:
    """Persist and validate the latest known state for each Bybit order."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        environment: str | None = None,
    ) -> None:
        self.path = Path(path or os.getenv("BYBIT_ORDER_STATE_FILE", "data/bybit_order_state.json"))
        configured = environment or _environment_from_exchange_mode(os.getenv("EXCHANGE_MODE", "sandbox"))
        self.environment = _normalize_environment(configured)
        self.max_event_lag_ms = min(
            max(int(os.getenv("BYBIT_ORDER_MAX_EVENT_LAG_MS", "15000")), 1_000),
            60_000,
        )
        self.max_future_skew_ms = min(
            max(int(os.getenv("BYBIT_ORDER_MAX_FUTURE_SKEW_MS", "1000")), 0),
            10_000,
        )
        self.max_tracked_orders = min(
            max(int(os.getenv("BYBIT_ORDER_MAX_TRACKED", "5000")), 100),
            10_000,
        )
        self._lock = threading.RLock()

    def ingest_message(
        self,
        message: Mapping[str, Any],
        *,
        received_at_ms: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("message must be an object")
        topic = str(message.get("topic", "")).strip()
        if topic not in _ALLOWED_TOPICS:
            raise ValueError("unsupported Bybit order topic")
        message_id = str(message.get("id", "")).strip()
        creation_time = _positive_int(message.get("creationTime"), "creationTime")
        current_ms = int(time.time() * 1000) if received_at_ms is None else _positive_int(
            received_at_ms, "received_at_ms"
        )
        _validate_event_time(
            creation_time,
            current_ms,
            self.max_event_lag_ms,
            self.max_future_skew_ms,
            "creationTime",
        )
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
                    state = _normalize_order(
                        raw,
                        message_id=message_id,
                        creation_time=creation_time,
                        received_at_ms=current_ms,
                        environment=self.environment,
                        max_event_lag_ms=self.max_event_lag_ms,
                        max_future_skew_ms=self.max_future_skew_ms,
                    )
                    existing_key = _find_existing_key(orders, state)
                    existing_raw = orders.get(existing_key) if existing_key else None
                    outcome, state_to_store = _merge_state(existing_raw, state)
                    storage_key = existing_key or _new_storage_key(state_to_store)
                    if outcome == "duplicate":
                        duplicates.append(storage_key)
                        continue
                    if existing_key is None and len(orders) >= self.max_tracked_orders:
                        raise ValueError("maximum tracked order count reached")
                    orders[storage_key] = state_to_store.to_dict()
                    accepted.append(storage_key)
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
            "environment": self.environment,
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
    """Require execution journal identity and business fields to match private state."""
    journal_orders = journal.get("orders", []) if isinstance(journal, Mapping) else []
    tracked_orders = tracker_snapshot.get("orders", []) if isinstance(tracker_snapshot, Mapping) else []
    if not isinstance(journal_orders, list) or not isinstance(tracked_orders, list):
        return {
            "status": "warning",
            "accepted_journal_orders": 0,
            "matched_open": [],
            "matched_terminal": [],
            "unresolved": [{"identity": "document", "reason": "journal or tracker order list is invalid"}],
            "restart_safe": False,
        }

    by_order_id: dict[str, Mapping[str, Any]] = {}
    by_link_id: dict[str, Mapping[str, Any]] = {}
    tracker_errors: list[dict[str, Any]] = []
    for index, item in enumerate(tracked_orders):
        if not isinstance(item, Mapping):
            tracker_errors.append({"identity": f"tracker-index:{index}", "reason": "tracker item is invalid"})
            continue
        order_id = str(item.get("order_id", "")).strip()
        link_id = str(item.get("order_link_id", "")).strip()
        if not order_id and not link_id:
            tracker_errors.append({"identity": f"tracker-index:{index}", "reason": "tracker identity is missing"})
            continue
        if order_id and order_id in by_order_id:
            tracker_errors.append({"identity": order_id, "reason": "duplicate order_id in tracker snapshot"})
        else:
            if order_id:
                by_order_id[order_id] = item
        if link_id and link_id in by_link_id:
            tracker_errors.append({"identity": link_id, "reason": "duplicate order_link_id in tracker snapshot"})
        else:
            if link_id:
                by_link_id[link_id] = item

    accepted_entries = [
        item
        for item in journal_orders
        if isinstance(item, Mapping) and item.get("status") == "accepted"
    ]
    matched_open: list[str] = []
    matched_terminal: list[str] = []
    unresolved: list[dict[str, Any]] = list(tracker_errors)

    for index, item in enumerate(accepted_entries):
        order_id = str(item.get("order_id", "")).strip()
        link_id = str(item.get("order_link_id", "")).strip()
        identity = order_id or link_id or f"journal-index:{index}"
        missing = [
            name
            for name in ("environment", "category", "symbol", "side", "quantity")
            if item.get(name) in (None, "")
        ]
        if not order_id and not link_id:
            missing.insert(0, "order_id_or_order_link_id")
        if missing:
            unresolved.append({"identity": identity, "reason": "missing journal fields", "fields": missing})
            continue

        tracked_by_order = by_order_id.get(order_id) if order_id else None
        tracked_by_link = by_link_id.get(link_id) if link_id else None
        if tracked_by_order is not None and tracked_by_link is not None and tracked_by_order is not tracked_by_link:
            unresolved.append({"identity": identity, "reason": "journal identifiers resolve to different orders"})
            continue
        tracked = tracked_by_order or tracked_by_link
        if tracked is None:
            unresolved.append({"identity": identity, "reason": "no private order state observed"})
            continue

        try:
            mismatches = _business_mismatches(item, tracked)
        except (TypeError, ValueError) as exc:
            unresolved.append({"identity": identity, "reason": f"invalid business fields: {exc}"})
            continue
        if mismatches:
            unresolved.append({"identity": identity, "reason": "business fields mismatch", "fields": mismatches})
            continue

        status = str(tracked.get("status", ""))
        if status in _TERMINAL_STATUSES:
            matched_terminal.append(identity)
        elif status in _OPEN_STATUSES:
            matched_open.append(identity)
        else:
            unresolved.append({"identity": identity, "reason": "unknown tracked status"})

    status = "ok" if not unresolved else "warning"
    return {
        "status": status,
        "accepted_journal_orders": len(accepted_entries),
        "matched_open": matched_open,
        "matched_terminal": matched_terminal,
        "unresolved": unresolved,
        "restart_safe": status == "ok",
    }


def _business_mismatches(journal: Mapping[str, Any], tracked: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    if _normalize_environment(journal.get("environment")) != _normalize_environment(tracked.get("environment")):
        mismatches.append("environment")
    if str(journal.get("category", "")).strip().lower() != str(tracked.get("category", "")).strip().lower():
        mismatches.append("category")
    if _symbol(journal.get("symbol")) != _symbol(tracked.get("symbol")):
        mismatches.append("symbol")
    journal_side = str(journal.get("side", "")).strip().title()
    tracked_side = str(tracked.get("side", "")).strip().title()
    if journal_side not in _ALLOWED_SIDES or tracked_side not in _ALLOWED_SIDES:
        raise ValueError("invalid side")
    if journal_side != tracked_side:
        mismatches.append("side")
    journal_qty = _number(journal.get("quantity"), "quantity", minimum=0.0, strict=True)
    tracked_qty = _number(tracked.get("qty"), "qty", minimum=0.0, strict=True)
    if abs(journal_qty - tracked_qty) > 1e-12:
        mismatches.append("quantity")
    return mismatches


def _normalize_order(
    raw: Any,
    *,
    message_id: str,
    creation_time: int,
    received_at_ms: int,
    environment: str,
    max_event_lag_ms: int,
    max_future_skew_ms: int,
) -> OrderState:
    if not isinstance(raw, Mapping):
        raise TypeError("order event must be an object")
    order_id = str(raw.get("orderId", "")).strip()
    order_link_id = str(raw.get("orderLinkId", "")).strip()
    if not order_id and not order_link_id:
        raise ValueError("orderId or orderLinkId is required")
    category = str(raw.get("category", "")).strip().lower()
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError("invalid category")
    symbol = _symbol(raw.get("symbol"))
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
    _validate_event_time(updated_time, received_at_ms, max_event_lag_ms, max_future_skew_ms, "updatedTime")
    return OrderState(
        order_id=order_id,
        order_link_id=order_link_id,
        environment=environment,
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


def _find_existing_key(orders: Mapping[str, Any], new: OrderState) -> str | None:
    matches: set[str] = set()
    for key, raw in orders.items():
        if not isinstance(raw, Mapping):
            raise ValueError("persisted order state is invalid")
        existing_order_id = str(raw.get("order_id", "")).strip()
        existing_link_id = str(raw.get("order_link_id", "")).strip()
        if new.order_id and existing_order_id == new.order_id:
            matches.add(str(key))
        if new.order_link_id and existing_link_id == new.order_link_id:
            matches.add(str(key))
    if len(matches) > 1:
        raise ValueError("orderId and orderLinkId resolve to different persisted orders")
    return next(iter(matches), None)


def _new_storage_key(state: OrderState) -> str:
    return state.order_id or f"link:{state.order_link_id}"


def _merge_state(existing_raw: Any, new: OrderState) -> tuple[str, OrderState]:
    if existing_raw is None:
        return "accepted", new
    if not isinstance(existing_raw, Mapping):
        raise ValueError("persisted order state is invalid")
    try:
        existing = OrderState(**dict(existing_raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("persisted order state is invalid") from exc

    for name in ("environment", "category", "symbol", "side"):
        if getattr(existing, name) != getattr(new, name):
            raise ValueError(f"order identity field changed: {name}")
    if existing.order_id and new.order_id and existing.order_id != new.order_id:
        raise ValueError("orderId changed for an existing orderLinkId")
    if existing.order_link_id and new.order_link_id and existing.order_link_id != new.order_link_id:
        raise ValueError("orderLinkId changed for an existing orderId")
    if abs(existing.qty - new.qty) > 1e-12:
        raise ValueError("order qty changed")
    if new.updated_time_ms < existing.updated_time_ms:
        raise ValueError("out-of-order updatedTime")
    if new.cum_exec_qty < existing.cum_exec_qty - 1e-12:
        raise ValueError("cumExecQty regression")

    merged = replace(
        new,
        order_id=existing.order_id or new.order_id,
        order_link_id=existing.order_link_id or new.order_link_id,
    )
    identity_enriched = (
        (not existing.order_id and bool(new.order_id))
        or (not existing.order_link_id and bool(new.order_link_id))
    )
    same_business_state = (
        new.status == existing.status
        and abs(new.cum_exec_qty - existing.cum_exec_qty) <= 1e-12
        and abs(new.avg_price - existing.avg_price) <= 1e-12
    )
    if same_business_state and not identity_enriched:
        return "duplicate", existing
    if new.updated_time_ms == existing.updated_time_ms and not identity_enriched:
        raise ValueError("conflicting event with identical updatedTime")
    if existing.terminal:
        raise ValueError("terminal order cannot transition to another state")
    if not same_business_state:
        allowed = _TRANSITIONS.get(existing.status, {existing.status})
        if new.status not in allowed:
            raise ValueError(f"invalid transition {existing.status}->{new.status}")
    return "accepted", merged


def _validate_event_time(value: int, received: int, max_lag: int, max_future: int, name: str) -> None:
    if value > received + max_future:
        raise ValueError(f"{name} is too far in the future")
    if received - value > max_lag:
        raise ValueError(f"{name} is stale")


def _normalize_environment(value: Any) -> str:
    clean = str(value or "").strip().lower()
    clean = {"sandbox": "testnet", "live": "mainnet"}.get(clean, clean)
    if clean not in _ALLOWED_ENVIRONMENTS:
        raise ValueError("invalid environment")
    return clean


def _environment_from_exchange_mode(value: Any) -> str:
    return _normalize_environment(value)


def _symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not symbol or len(symbol) > 80 or not symbol.isalnum():
        raise ValueError("invalid symbol")
    return symbol


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
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    if parsed < minimum or (strict and parsed <= minimum):
        comparator = "greater than" if strict else "at least"
        raise ValueError(f"{name} must be {comparator} {minimum}")
    return parsed
