"""Fail-closed private Bybit order state backed by the canonical project database.

The module validates and stores private order events. It never opens a network
connection and never submits, changes, or cancels an order.
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

from storage import ProjectDatabase, VersionConflict

_OPEN = {"Untriggered", "New", "PartiallyFilled"}
_CLOSED = {"Triggered", "Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}
_ALLOWED = _OPEN | _CLOSED
_TERMINAL = {"Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}
_TRANSITIONS = {
    "Untriggered": {"Untriggered", "Triggered", "New", "Cancelled", "Rejected", "Deactivated"},
    "Triggered": {"Triggered", "New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "Deactivated"},
    "New": {"New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled", "PartiallyFilledCanceled"},
}
_CATEGORIES = {"spot", "linear", "inverse", "option"}
_TOPICS = {"order", "order.spot", "order.linear", "order.inverse", "order.option"}
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
    def managed(self) -> bool:
        return self.order_link_id.startswith("sai_")

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitOrderStateStore:
    """Atomic, alias-aware state for testnet or mainnet private order events."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        environment: str | None = None,
        max_message_lag_seconds: float | None = None,
        max_future_skew_ms: int | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.environment = _environment(environment or os.getenv("EXCHANGE_MODE", "sandbox"))
        configured_lag = (
            max_message_lag_seconds
            if max_message_lag_seconds is not None
            else _finite(os.getenv("BYBIT_PRIVATE_EVENT_MAX_LAG_SECONDS", "30"), "max message lag")
        )
        self.max_message_lag_ms = int(min(max(configured_lag, 1.0), 300.0) * 1000)
        configured_skew = (
            max_future_skew_ms
            if max_future_skew_ms is not None
            else int(os.getenv("BYBIT_PRIVATE_EVENT_MAX_FUTURE_SKEW_MS", "1000"))
        )
        self.max_future_skew_ms = min(max(int(configured_skew), 0), 5_000)
        self.namespace = "bybit_private_orders"
        self.key = self.environment

    def ingest_message(self, message: Mapping[str, Any], *, received_at_ms: int | None = None) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("private order message must be an object")
        topic = str(message.get("topic", "")).strip()
        if topic not in _TOPICS:
            raise ValueError("unsupported private order topic")
        received = _positive_int(
            received_at_ms if received_at_ms is not None else int(time.time() * 1000),
            "received_at_ms",
        )
        creation = _positive_int(message.get("creationTime"), "creationTime")
        if creation > received + self.max_future_skew_ms:
            raise ValueError("message creationTime is in the future")
        if received - creation > self.max_message_lag_ms:
            raise ValueError("private order message is too old or replayed")
        rows = message.get("data")
        if not isinstance(rows, list) or not rows:
            raise ValueError("private order data must be a non-empty list")
        message_id = _identifier(message.get("id") or f"msg-{creation}", "message id")
        normalized = [
            _normalize_row(
                row,
                topic=topic,
                environment=self.environment,
                message_id=message_id,
                message_creation_ms=creation,
                received_at_ms=received,
                max_message_lag_ms=self.max_message_lag_ms,
                max_future_skew_ms=self.max_future_skew_ms,
            )
            for row in rows
        ]

        for _attempt in range(5):
            current = self.database.get_json(self.namespace, self.key)
            version = int(current["version"]) if current else 0
            document = _document(current["value"] if current else None, environment=self.environment)
            accepted: list[str] = []
            duplicates: list[str] = []
            for state in normalized:
                outcome, canonical = _merge_into_document(document, state)
                (accepted if outcome == "accepted" else duplicates).append(canonical)
            document["last_message_creation_ms"] = max(int(document.get("last_message_creation_ms", 0)), creation)
            document["updated_at_ms"] = received
            try:
                new_version = self.database.put_json(
                    self.namespace,
                    self.key,
                    document,
                    expected_version=version,
                )
                return {
                    "status": "ok",
                    "environment": self.environment,
                    "accepted": accepted,
                    "duplicates": duplicates,
                    "version": new_version,
                }
            except VersionConflict:
                continue
        raise RuntimeError("private order state update conflicted repeatedly")

    def snapshot(self) -> dict[str, Any]:
        current = self.database.get_json(self.namespace, self.key)
        document = _document(current["value"] if current else None, environment=self.environment)
        orders = [_state_from_mapping(raw).to_dict() for raw in document["orders"].values()]
        orders.sort(key=lambda item: (int(item["updated_time_ms"]), item["order_link_id"], item["order_id"]))
        return {
            "status": "ok",
            "environment": self.environment,
            "version": int(current["version"]) if current else 0,
            "updated_at_ms": int(document.get("updated_at_ms", 0)),
            "orders": orders,
            "open_orders": [item for item in orders if item["status"] in _OPEN],
            "managed_orders": [item for item in orders if str(item["order_link_id"]).startswith("sai_")],
        }

    def reconcile(self, journal: Mapping[str, Any] | list[Any]) -> dict[str, Any]:
        rows = journal.get("orders", []) if isinstance(journal, Mapping) else journal
        if not isinstance(rows, list):
            raise RuntimeError("execution journal must contain an orders list")
        snapshot = self.snapshot()
        managed = [item for item in snapshot["orders"] if str(item.get("order_link_id", "")).startswith("sai_")]
        journal_by_link: dict[str, dict[str, Any]] = {}
        journal_by_order: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                errors.append(f"journal row {index} is not an object")
                continue
            normalized_row = dict(raw)
            link = str(normalized_row.get("order_link_id") or normalized_row.get("orderLinkId") or "").strip()
            order_id = str(normalized_row.get("order_id") or normalized_row.get("orderId") or "").strip()
            if link:
                if link in journal_by_link and journal_by_link[link] != normalized_row:
                    errors.append(f"duplicate journal orderLinkId {link}")
                journal_by_link[link] = normalized_row
            if order_id:
                if order_id in journal_by_order and journal_by_order[order_id] != normalized_row:
                    errors.append(f"duplicate journal orderId {order_id}")
                journal_by_order[order_id] = normalized_row

        matched: list[str] = []
        for order in managed:
            link = str(order["order_link_id"])
            order_id = str(order["order_id"])
            row = journal_by_link.get(link)
            if row is None:
                errors.append(f"managed private order {link} is missing from execution journal")
                continue
            journal_order_id = str(row.get("order_id") or row.get("orderId") or "").strip()
            if order_id and journal_order_id != order_id:
                errors.append(f"orderId mismatch for {link}")
            if journal_order_id and journal_by_order.get(journal_order_id) != row:
                errors.append(f"journal identifiers resolve inconsistently for {link}")
            expected_environment = _journal_environment(row.get("environment") or row.get("mode"))
            if expected_environment and expected_environment != order["environment"]:
                errors.append(f"environment mismatch for {link}")
            for journal_key, order_key, transform in (
                ("category", "category", lambda value: str(value).strip().lower()),
                ("symbol", "symbol", lambda value: str(value).strip().upper()),
                ("side", "side", lambda value: str(value).strip().title()),
            ):
                if journal_key not in row:
                    errors.append(f"journal field {journal_key} missing for {link}")
                    continue
                if transform(row[journal_key]) != transform(order[order_key]):
                    errors.append(f"{journal_key} mismatch for {link}")
            quantity = row.get("quantity", row.get("qty"))
            try:
                if abs(_finite(quantity, "journal quantity") - float(order["qty"])) > _TOLERANCE:
                    errors.append(f"quantity mismatch for {link}")
            except (TypeError, ValueError):
                errors.append(f"journal quantity invalid for {link}")
            matched.append(link)

        return {
            "status": "ok" if not errors else "blocked",
            "restart_safe": not errors,
            "environment": self.environment,
            "matched_order_link_ids": matched,
            "errors": errors,
            "private_order_count": len(snapshot["orders"]),
            "managed_order_count": len(managed),
            "journal_order_count": len(rows),
        }


def _merge_into_document(document: dict[str, Any], state: OrderState) -> tuple[str, str]:
    aliases: dict[str, str] = document["aliases"]
    orders: dict[str, dict[str, Any]] = document["orders"]
    candidates = {
        aliases[alias]
        for alias in (_order_alias(state.order_id), _link_alias(state.order_link_id))
        if alias and alias in aliases
    }
    if len(candidates) > 1:
        raise RuntimeError("orderId and orderLinkId resolve to different orders")
    canonical = next(iter(candidates), None)
    if canonical is None:
        canonical = _link_alias(state.order_link_id) or _order_alias(state.order_id)
    if not canonical:
        raise ValueError("order has no canonical identity")
    existing = _state_from_mapping(orders[canonical]) if canonical in orders else None
    outcome, merged = _merge(existing, state)
    orders[canonical] = merged.to_dict()
    for alias in (_order_alias(merged.order_id), _link_alias(merged.order_link_id)):
        if not alias:
            continue
        bound = aliases.get(alias)
        if bound and bound != canonical:
            raise RuntimeError("order alias collision")
        aliases[alias] = canonical
    return outcome, canonical


def _merge(existing: OrderState | None, new: OrderState) -> tuple[str, OrderState]:
    if existing is None:
        return "accepted", new
    for field in ("environment", "category", "symbol", "side", "qty", "created_time_ms"):
        old = getattr(existing, field)
        current = getattr(new, field)
        if isinstance(old, float):
            if abs(old - current) > _TOLERANCE:
                raise ValueError(f"immutable field changed: {field}")
        elif old != current:
            raise ValueError(f"immutable field changed: {field}")
    if existing.order_id and new.order_id and existing.order_id != new.order_id:
        raise ValueError("orderId changed")
    if existing.order_link_id and new.order_link_id and existing.order_link_id != new.order_link_id:
        raise ValueError("orderLinkId changed")
    if new.updated_time_ms < existing.updated_time_ms:
        raise ValueError("out-of-order updatedTime")

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
    identity_enriched = (not existing.order_id and bool(merged.order_id)) or (
        not existing.order_link_id and bool(merged.order_link_id)
    )
    if existing.terminal:
        if not same_execution:
            raise ValueError("terminal order cannot change")
        return ("accepted", merged) if identity_enriched else ("duplicate", existing)
    if new.cum_exec_qty < existing.cum_exec_qty - _TOLERANCE:
        raise ValueError("cumExecQty regression")
    if new.updated_time_ms == existing.updated_time_ms:
        if same_execution and identity_enriched:
            return "accepted", merged
        if same_execution:
            return "duplicate", existing
        raise ValueError("conflicting state at identical updatedTime")
    if merged.status not in _TRANSITIONS.get(existing.status, {existing.status}):
        raise ValueError(f"invalid transition {existing.status}->{merged.status}")
    return "accepted", merged


def _normalize_row(
    row: Any,
    *,
    topic: str,
    environment: str,
    message_id: str,
    message_creation_ms: int,
    received_at_ms: int,
    max_message_lag_ms: int,
    max_future_skew_ms: int,
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
    if not symbol or not symbol.isalnum():
        raise ValueError("invalid symbol")
    side = str(row.get("side", "")).strip().title()
    if side not in {"Buy", "Sell"}:
        raise ValueError("invalid side")
    status = str(row.get("orderStatus", "")).strip()
    if status not in _ALLOWED:
        raise ValueError("invalid orderStatus")
    qty = _finite(row.get("qty"), "qty", positive=True)
    executed = _finite(row.get("cumExecQty", 0), "cumExecQty")
    average = _finite(row.get("avgPrice") or 0, "avgPrice")
    if executed < 0 or average < 0 or executed > qty + _TOLERANCE:
        raise ValueError("invalid execution quantities")
    created = _positive_int(row.get("createdTime"), "createdTime")
    updated = _positive_int(row.get("updatedTime"), "updatedTime")
    if updated < created:
        raise ValueError("updatedTime precedes createdTime")
    if max(created, updated) > received_at_ms + max_future_skew_ms:
        raise ValueError("order timestamp is in the future")
    if updated > message_creation_ms + max_future_skew_ms:
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
    _validate_semantics(state)
    return state


def _validate_semantics(state: OrderState) -> None:
    executed, qty, average = state.cum_exec_qty, state.qty, state.avg_price
    if executed > _TOLERANCE and average <= 0:
        raise ValueError("avgPrice must be positive after execution")
    if executed <= _TOLERANCE and average > _TOLERANCE:
        raise ValueError("avgPrice must be zero before execution")
    if state.status == "Filled" and abs(executed - qty) > _TOLERANCE:
        raise ValueError("Filled requires cumExecQty equal to qty")
    if state.status in {"PartiallyFilled", "PartiallyFilledCanceled"} and not (
        _TOLERANCE < executed < qty - _TOLERANCE
    ):
        raise ValueError(f"{state.status} requires partial execution")
    if state.status == "PartiallyFilledCanceled" and state.category != "spot":
        raise ValueError("PartiallyFilledCanceled is spot-only")
    if state.status == "Cancelled" and executed >= qty - _TOLERANCE:
        raise ValueError("Cancelled cannot be fully executed")
    if state.status == "Cancelled" and state.category == "spot" and executed > _TOLERANCE:
        raise ValueError("partial spot cancellation requires PartiallyFilledCanceled")
    if state.status in {"Untriggered", "Triggered", "New", "Rejected", "Deactivated"} and executed > _TOLERANCE:
        raise ValueError(f"{state.status} cannot report execution")


def _document(value: Any, *, environment: str) -> dict[str, Any]:
    if value is None:
        return {
            "environment": environment,
            "orders": {},
            "aliases": {},
            "last_message_creation_ms": 0,
            "updated_at_ms": 0,
        }
    if not isinstance(value, dict) or value.get("environment") != environment:
        raise RuntimeError("private order state document is invalid")
    if not isinstance(value.get("orders"), dict) or not isinstance(value.get("aliases"), dict):
        raise RuntimeError("private order state structure is invalid")
    orders = value["orders"]
    aliases = value["aliases"]
    expected_aliases: dict[str, str] = {}
    for canonical, raw in orders.items():
        if not isinstance(canonical, str) or not isinstance(raw, Mapping):
            raise RuntimeError("private order state record is invalid")
        state = _state_from_mapping(raw)
        if state.environment != environment:
            raise RuntimeError("persisted order environment mismatch")
        _validate_semantics(state)
        valid_canonical = {_order_alias(state.order_id), _link_alias(state.order_link_id)} - {""}
        if canonical not in valid_canonical:
            raise RuntimeError("canonical order key does not match identifiers")
        for alias in valid_canonical:
            if alias in expected_aliases and expected_aliases[alias] != canonical:
                raise RuntimeError("persisted order alias collision")
            expected_aliases[alias] = canonical
    if aliases != expected_aliases:
        raise RuntimeError("persisted aliases do not match order records")
    return {
        "environment": environment,
        "orders": {str(key): dict(raw) for key, raw in orders.items()},
        "aliases": dict(aliases),
        "last_message_creation_ms": int(value.get("last_message_creation_ms", 0)),
        "updated_at_ms": int(value.get("updated_at_ms", 0)),
    }


def _state_from_mapping(raw: Mapping[str, Any]) -> OrderState:
    try:
        state = OrderState(**dict(raw))
    except TypeError as exc:
        raise RuntimeError("persisted order state is invalid") from exc
    for name in ("qty", "cum_exec_qty", "avg_price"):
        _finite(getattr(state, name), f"persisted {name}", positive=name == "qty")
    for name in ("created_time_ms", "updated_time_ms", "message_creation_time_ms"):
        _positive_int(getattr(state, name), f"persisted {name}")
    if state.status not in _ALLOWED or state.category not in _CATEGORIES or state.side not in {"Buy", "Sell"}:
        raise RuntimeError("persisted order state contains invalid enums")
    if not state.symbol or not state.symbol.isalnum() or state.symbol != state.symbol.upper():
        raise RuntimeError("persisted order symbol is invalid")
    return state


def _environment(value: Any) -> str:
    clean = str(value).strip().lower()
    if clean in {"sandbox", "testnet"}:
        return "testnet"
    if clean in {"live", "mainnet", "live_read_only"}:
        return "mainnet"
    raise ValueError("environment must be testnet or mainnet")


def _journal_environment(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not clean:
        return ""
    return _environment(clean)


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return parsed


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be positive")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _identifier(value: Any, name: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 128 or not all(char.isalnum() or char in "._:-" for char in text):
        raise ValueError(f"invalid {name}")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    return _identifier(text, name) if text else ""


def _order_alias(order_id: str) -> str:
    return f"order:{order_id}" if order_id else ""


def _link_alias(link_id: str) -> str:
    return f"link:{link_id}" if link_id else ""


__all__ = ["BybitOrderStateStore", "OrderState"]
