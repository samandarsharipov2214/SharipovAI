"""Fail-closed private Bybit order state and restart reconciliation.

This module never opens a socket and never submits, amends, or cancels an order.
It validates already-received private order events, persists a canonical state,
and blocks restart when execution evidence cannot be reconciled.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import isfinite
from pathlib import Path
from typing import Any

_OPEN = {"Untriggered", "Triggered", "New", "PartiallyFilled"}
_TERMINAL = {"Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}
_ALLOWED = _OPEN | _TERMINAL
_TRANSITIONS = {
    "Untriggered": {"Untriggered", "Triggered", "New", "Cancelled", "Rejected", "Deactivated"},
    "Triggered": {"Triggered", "New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "Deactivated"},
    "New": {"New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled", "PartiallyFilledCanceled"},
}
_CATEGORIES = {"spot", "linear", "inverse", "option"}
_SIDES = {"Buy", "Sell"}
_TOPICS = {"order", "order.spot", "order.linear", "order.inverse", "order.option"}
_ENVIRONMENTS = {"testnet", "mainnet"}
_TOLERANCE = 1e-12


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
        return self.status in _TERMINAL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitOrderStateStore:
    """Canonical, alias-aware state store for private order events."""

    def __init__(self, path: str | Path | None = None, *, environment: str | None = None) -> None:
        self.path = Path(path or os.getenv("BYBIT_ORDER_STATE_FILE", "data/bybit_order_state.json"))
        self.environment = _environment(environment or os.getenv("EXCHANGE_MODE", "sandbox"))
        configured_lag = _finite_float(os.getenv("BYBIT_PRIVATE_EVENT_MAX_LAG_SECONDS", "30"), "max lag")
        self.max_message_lag_ms = int(min(max(configured_lag, 1.0), 300.0) * 1000)
        future_skew = _integer(os.getenv("BYBIT_PRIVATE_EVENT_MAX_FUTURE_SKEW_MS", "1000"), "future skew")
        self.max_future_skew_ms = min(max(future_skew, 0), 5000)
        self._lock = threading.RLock()

    def ingest_message(self, message: Mapping[str, Any], *, received_at_ms: int | None = None) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("message must be an object")
        topic = str(message.get("topic", "")).strip()
        if topic not in _TOPICS:
            raise ValueError("unsupported private order topic")
        now_ms = _positive_int(
            received_at_ms if received_at_ms is not None else int(time.time() * 1000),
            "received_at_ms",
        )
        creation_ms = _positive_int(message.get("creationTime"), "creationTime")
        if creation_ms > now_ms + self.max_future_skew_ms:
            raise ValueError("message creationTime is in the future")
        if now_ms - creation_ms > self.max_message_lag_ms:
            raise ValueError("private order message is too old or replayed")
        rows = message.get("data")
        if not isinstance(rows, list) or not rows:
            raise ValueError("data must be a non-empty list")
        message_id = _optional_identifier(message.get("id"), "message id")

        with self._lock:
            document = self._load()
            orders = dict(document["orders"])
            aliases = dict(document["aliases"])
            accepted: list[str] = []
            duplicates: list[str] = []
            rejected: list[dict[str, Any]] = []

            for index, row in enumerate(rows):
                candidate_orders = dict(orders)
                candidate_aliases = dict(aliases)
                try:
                    state = _normalize(
                        row,
                        topic=topic,
                        environment=self.environment,
                        message_id=message_id,
                        message_creation_ms=creation_ms,
                        received_at_ms=now_ms,
                        max_message_lag_ms=self.max_message_lag_ms,
                        future_skew_ms=self.max_future_skew_ms,
                    )
                    canonical = _resolve_canonical(candidate_aliases, state.order_id, state.order_link_id)
                    existing_raw = candidate_orders.get(canonical) if canonical else None
                    if canonical is None:
                        canonical = f"order:{state.order_id}" if state.order_id else f"link:{state.order_link_id}"
                    outcome, merged = _merge(existing_raw, state)
                    if outcome == "duplicate":
                        duplicates.append(canonical)
                    else:
                        candidate_orders[canonical] = merged.to_dict()
                        accepted.append(canonical)
                    _bind_aliases(candidate_aliases, canonical, merged.order_id, merged.order_link_id)
                    orders, aliases = candidate_orders, candidate_aliases
                except (TypeError, ValueError, RuntimeError) as exc:
                    rejected.append({"index": index, "reason": str(exc)})

            if accepted or aliases != document["aliases"]:
                self._write({"orders": orders, "aliases": aliases, "updated_at_ms": now_ms})

        return {
            "status": "ok" if not rejected else "partial" if accepted or duplicates else "blocked",
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
            "tracked_orders": len(orders),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            document = self._load()
        values = [dict(value) for value in document["orders"].values()]
        return {
            "status": "ok",
            "environment": self.environment,
            "updated_at_ms": document.get("updated_at_ms"),
            "tracked_orders": len(values),
            "open_orders": [value for value in values if value.get("status") in _OPEN],
            "terminal_orders": [value for value in values if value.get("status") in _TERMINAL],
            "orders": values,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": {}, "aliases": {}, "updated_at_ms": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"order state file is unreadable: {type(exc).__name__}") from exc
        _validate_document(data, environment=self.environment)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        _validate_document(data, environment=self.environment)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def reconcile_execution_journal(journal: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Require identity and immutable execution fields to match after restart."""
    journal_rows = journal.get("orders", []) if isinstance(journal, Mapping) else []
    tracked_rows = snapshot.get("orders", []) if isinstance(snapshot, Mapping) else []
    if not isinstance(journal_rows, list) or not isinstance(tracked_rows, list):
        raise TypeError("journal and snapshot must contain order lists")

    by_order: dict[str, int] = {}
    by_link: dict[str, int] = {}
    normalized_tracked: list[Mapping[str, Any]] = []
    for index, row in enumerate(tracked_rows):
        if not isinstance(row, Mapping):
            raise RuntimeError("tracker snapshot contains an invalid order")
        normalized_tracked.append(row)
        order_id = str(row.get("order_id", "")).strip()
        link_id = str(row.get("order_link_id", "")).strip()
        if not order_id and not link_id:
            raise RuntimeError("tracker snapshot order has no identity")
        if order_id:
            if order_id in by_order:
                raise RuntimeError("tracker snapshot contains duplicate order_id")
            by_order[order_id] = index
        if link_id:
            if link_id in by_link:
                raise RuntimeError("tracker snapshot contains duplicate order_link_id")
            by_link[link_id] = index

    unresolved: list[dict[str, Any]] = []
    matched_open: list[str] = []
    matched_terminal: list[str] = []
    matched_indices: set[int] = set()
    accepted = [row for row in journal_rows if isinstance(row, Mapping) and row.get("status") == "accepted"]
    for index, row in enumerate(accepted):
        order_id = str(row.get("order_id", "")).strip()
        link_id = str(row.get("order_link_id", "")).strip()
        identity = order_id or link_id or f"journal-index:{index}"
        order_index = by_order.get(order_id) if order_id else None
        link_index = by_link.get(link_id) if link_id else None
        if order_index is not None and link_index is not None and order_index != link_index:
            unresolved.append({"identity": identity, "reason": "journal identifiers resolve to different private orders"})
            continue
        tracked_index = order_index if order_index is not None else link_index
        if tracked_index is None:
            unresolved.append({"identity": identity, "reason": "private order state missing"})
            continue
        if tracked_index in matched_indices:
            unresolved.append({"identity": identity, "reason": "multiple journal rows resolve to one private order"})
            continue
        tracked = normalized_tracked[tracked_index]
        mismatches = _reconciliation_mismatches(row, tracked)
        if mismatches:
            unresolved.append({"identity": identity, "reason": "field mismatch", "fields": mismatches})
            continue
        matched_indices.add(tracked_index)
        if str(tracked.get("status")) in _TERMINAL:
            matched_terminal.append(identity)
        else:
            matched_open.append(identity)

    for index, tracked in enumerate(normalized_tracked):
        if str(tracked.get("status")) not in _OPEN or index in matched_indices:
            continue
        identity = str(tracked.get("order_id") or tracked.get("order_link_id") or f"private-index:{index}")
        unresolved.append({"identity": identity, "reason": "private open order missing from execution journal"})

    return {
        "status": "ok" if not unresolved else "blocked",
        "accepted_journal_orders": len(accepted),
        "matched_open": matched_open,
        "matched_terminal": matched_terminal,
        "unresolved": unresolved,
        "restart_safe": not unresolved,
    }


def _normalize(
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
    order_id = _optional_identifier(row.get("orderId"), "orderId")
    link_id = _optional_identifier(row.get("orderLinkId"), "orderLinkId")
    if not order_id and not link_id:
        raise ValueError("orderId or orderLinkId is required")
    category = str(row.get("category", "")).strip().lower()
    if category not in _CATEGORIES:
        raise ValueError("invalid category")
    if "." in topic and topic.split(".", 1)[1] != category:
        raise ValueError("topic and category mismatch")
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol or len(symbol) > 80 or not all(char.isalnum() or char in "-_" for char in symbol):
        raise ValueError("invalid symbol")
    side = str(row.get("side", "")).strip().title()
    if side not in _SIDES:
        raise ValueError("invalid side")
    status = str(row.get("orderStatus", "")).strip()
    if status not in _ALLOWED:
        raise ValueError("invalid orderStatus")
    qty = _number(row.get("qty"), "qty", positive=True)
    executed = _number(row.get("cumExecQty", 0), "cumExecQty")
    if executed > qty + _TOLERANCE:
        raise ValueError("cumExecQty exceeds qty")
    average = _number(row.get("avgPrice") or 0, "avgPrice")
    created = _positive_int(row.get("createdTime"), "createdTime")
    updated = _positive_int(row.get("updatedTime"), "updatedTime")
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
    _validate_state_semantics(state)
    return state


def _resolve_canonical(aliases: Mapping[str, str], order_id: str, link_id: str) -> str | None:
    candidates = set()
    if order_id and aliases.get(f"order:{order_id}"):
        candidates.add(aliases[f"order:{order_id}"])
    if link_id and aliases.get(f"link:{link_id}"):
        candidates.add(aliases[f"link:{link_id}"])
    if len(candidates) > 1:
        raise RuntimeError("orderId and orderLinkId resolve to different orders")
    return next(iter(candidates), None)


def _bind_aliases(aliases: dict[str, str], canonical: str, order_id: str, link_id: str) -> None:
    for alias in ([f"order:{order_id}"] if order_id else []) + ([f"link:{link_id}"] if link_id else []):
        existing = aliases.get(alias)
        if existing and existing != canonical:
            raise RuntimeError("order alias collision")
        aliases[alias] = canonical


def _merge(existing_raw: Any, new: OrderState) -> tuple[str, OrderState]:
    if existing_raw is None:
        return "accepted", new
    if not isinstance(existing_raw, Mapping):
        raise RuntimeError("persisted order state is invalid")
    try:
        existing = OrderState(**dict(existing_raw))
    except TypeError as exc:
        raise RuntimeError("persisted order state is invalid") from exc
    immutable = ("environment", "category", "symbol", "side", "qty", "created_time_ms")
    for field in immutable:
        old_value = getattr(existing, field)
        new_value = getattr(new, field)
        if isinstance(old_value, float):
            if abs(old_value - new_value) > _TOLERANCE:
                raise ValueError(f"immutable field changed: {field}")
        elif old_value != new_value:
            raise ValueError(f"immutable field changed: {field}")
    if existing.order_id and new.order_id and existing.order_id != new.order_id:
        raise ValueError("orderId changed")
    if existing.order_link_id and new.order_link_id and existing.order_link_id != new.order_link_id:
        raise ValueError("orderLinkId changed")
    if new.updated_time_ms < existing.updated_time_ms:
        raise ValueError("out-of-order updatedTime")
    if new.cum_exec_qty < existing.cum_exec_qty - _TOLERANCE:
        raise ValueError("cumExecQty regression")

    merged = replace(
        new,
        order_id=new.order_id or existing.order_id,
        order_link_id=new.order_link_id or existing.order_link_id,
    )
    same_execution = (
        merged.status == existing.status
        and abs(merged.cum_exec_qty - existing.cum_exec_qty) <= _TOLERANCE
        and abs(merged.avg_price - existing.avg_price) <= _TOLERANCE
    )
    identity_enriched = (
        (not existing.order_id and bool(merged.order_id))
        or (not existing.order_link_id and bool(merged.order_link_id))
    )

    if existing.terminal:
        if not same_execution:
            raise ValueError("terminal order cannot change")
        if merged.updated_time_ms == existing.updated_time_ms and not identity_enriched:
            return "duplicate", existing
        return "accepted", merged

    if merged.updated_time_ms == existing.updated_time_ms:
        if same_execution and identity_enriched:
            return "accepted", merged
        if same_execution:
            return "duplicate", existing
        raise ValueError("conflicting state at identical updatedTime")
    if merged.status not in _TRANSITIONS.get(existing.status, {existing.status}):
        raise ValueError(f"invalid transition {existing.status}->{merged.status}")
    return "accepted", merged


def _validate_state_semantics(state: OrderState) -> None:
    executed = state.cum_exec_qty
    qty = state.qty
    average = state.avg_price
    if executed > _TOLERANCE and average <= 0:
        raise ValueError("avgPrice must be positive after execution")
    if executed <= _TOLERANCE and average > _TOLERANCE:
        raise ValueError("avgPrice must be zero before execution")
    if state.status == "Filled" and abs(executed - qty) > _TOLERANCE:
        raise ValueError("Filled requires cumExecQty equal to qty")
    if state.status in {"PartiallyFilled", "PartiallyFilledCanceled"} and not (
        _TOLERANCE < executed < qty - _TOLERANCE
    ):
        raise ValueError(f"{state.status} requires a partial executed quantity")
    if state.status == "Cancelled" and executed >= qty - _TOLERANCE:
        raise ValueError("Cancelled cannot report a fully executed quantity")
    if state.status in {"Untriggered", "Triggered", "New", "Rejected", "Deactivated"} and executed > _TOLERANCE:
        raise ValueError(f"{state.status} cannot report executed quantity")


def _validate_document(data: Any, *, environment: str) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("orders"), dict) or not isinstance(data.get("aliases"), dict):
        raise RuntimeError("order state file has invalid structure")
    if data.get("updated_at_ms") is not None:
        _positive_int(data.get("updated_at_ms"), "persisted updated_at_ms")
    expected_aliases: dict[str, str] = {}
    for canonical, raw in data["orders"].items():
        if not isinstance(canonical, str) or not canonical.startswith(("order:", "link:")):
            raise RuntimeError("order state contains an invalid canonical key")
        if not isinstance(raw, dict):
            raise RuntimeError("order state contains an invalid record")
        try:
            state = OrderState(**raw)
        except TypeError as exc:
            raise RuntimeError("order state contains an invalid record") from exc
        if state.environment != environment:
            raise RuntimeError("persisted order environment mismatch")
        if not state.order_id and not state.order_link_id:
            raise RuntimeError("persisted order has no identity")
        try:
            _validate_state_semantics(state)
        except ValueError as exc:
            raise RuntimeError(f"persisted order state is inconsistent: {exc}") from exc
        for alias in ([f"order:{state.order_id}"] if state.order_id else []) + (
            [f"link:{state.order_link_id}"] if state.order_link_id else []
        ):
            existing = expected_aliases.get(alias)
            if existing and existing != canonical:
                raise RuntimeError("persisted order aliases collide")
            expected_aliases[alias] = canonical
    aliases = data["aliases"]
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in aliases.items()):
        raise RuntimeError("order state aliases are invalid")
    if aliases != expected_aliases:
        raise RuntimeError("order state aliases do not match order records")


def _reconciliation_mismatches(journal: Mapping[str, Any], tracked: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    environment = str(journal.get("environment") or journal.get("mode") or "").lower()
    environment = "testnet" if environment in {"sandbox", "testnet"} else environment
    checks = {
        "environment": environment,
        "category": str(journal.get("category", "")).lower(),
        "symbol": str(journal.get("symbol", "")).upper(),
        "side": str(journal.get("side", "")).title(),
    }
    for field, expected in checks.items():
        if not expected or str(tracked.get(field, "")) != expected:
            mismatches.append(field)
    try:
        journal_qty = float(journal.get("quantity", journal.get("qty")))
        if not isfinite(journal_qty) or abs(journal_qty - float(tracked.get("qty", -1))) > _TOLERANCE:
            mismatches.append("qty")
    except (TypeError, ValueError):
        mismatches.append("qty")
    return mismatches


def _environment(value: str) -> str:
    clean = str(value).strip().lower()
    clean = "testnet" if clean == "sandbox" else clean
    if clean not in _ENVIRONMENTS:
        raise ValueError("environment must be testnet or mainnet")
    return clean


def _optional_identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 128 or not all(char.isalnum() or char in "._:-" for char in text):
        raise ValueError(f"{name} has invalid format")
    return text


def _positive_int(value: Any, name: str) -> int:
    parsed = _integer(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    return parsed


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    parsed = _finite_float(value, name)
    if parsed < 0 or (positive and parsed <= 0):
        raise ValueError(f"{name} is outside the allowed range")
    return parsed
