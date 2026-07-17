"""Immutable private Bybit execution-fill ledger backed by ProjectDatabase.

The store accepts only authenticated private ``execution`` topic messages. Each
``execId`` is write-once. Exact WebSocket replays are deduplicated, while a
conflicting reuse of an execution identity fails closed. The module has no
network or order-write capability.
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from storage import ProjectDatabase, VersionConflict

_TOPICS = {"execution", "execution.spot", "execution.linear", "execution.inverse", "execution.option"}
_CATEGORIES = {"spot", "linear", "inverse", "option"}
_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class ExecutionFill:
    environment: str
    exec_id: str
    order_id: str
    order_link_id: str
    category: str
    symbol: str
    side: str
    exec_price: float
    exec_quantity: float
    exec_value: float
    exec_fee: float
    fee_rate: float
    fee_currency: str
    is_maker: bool
    exec_time_ms: int
    sequence: int
    message_creation_time_ms: int
    message_id: str

    @property
    def managed(self) -> bool:
        return self.order_link_id.startswith("sai_")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitExecutionStateStore:
    """Persist actual execution fees and partial fills exactly once."""

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
        lag = (
            float(max_message_lag_seconds)
            if max_message_lag_seconds is not None
            else _finite(os.getenv("BYBIT_PRIVATE_EVENT_MAX_LAG_SECONDS", "30"), "max message lag")
        )
        self.max_message_lag_ms = int(min(max(lag, 1.0), 300.0) * 1000)
        skew = (
            int(max_future_skew_ms)
            if max_future_skew_ms is not None
            else int(os.getenv("BYBIT_PRIVATE_EVENT_MAX_FUTURE_SKEW_MS", "1000"))
        )
        self.max_future_skew_ms = min(max(skew, 0), 5_000)
        self.namespace = "bybit_private_executions"
        self.key = self.environment

    def ingest_message(
        self,
        message: Mapping[str, Any],
        *,
        received_at_ms: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("private execution message must be an object")
        topic = str(message.get("topic", "")).strip()
        if topic not in _TOPICS:
            raise ValueError("unsupported private execution topic")
        received = _positive_int(
            received_at_ms if received_at_ms is not None else int(time.time() * 1000),
            "received_at_ms",
        )
        creation = _positive_int(message.get("creationTime"), "creationTime")
        if creation > received + self.max_future_skew_ms:
            raise ValueError("execution message creationTime is in the future")
        if received - creation > self.max_message_lag_ms:
            raise ValueError("private execution message is too old or replayed")
        rows = message.get("data")
        if not isinstance(rows, list) or not rows:
            raise ValueError("private execution data must be a non-empty list")
        message_id = _identifier(message.get("id") or f"exec-msg-{creation}", "message id")
        fills = [
            _normalize_fill(
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
            replays: list[str] = []
            for fill in fills:
                existing = document["fills"].get(fill.exec_id)
                if existing is None:
                    document["fills"][fill.exec_id] = fill.to_dict()
                    accepted.append(fill.exec_id)
                elif _fill_from_mapping(existing) == fill:
                    replays.append(fill.exec_id)
                else:
                    document["conflicting_duplicate_count"] = int(
                        document.get("conflicting_duplicate_count", 0)
                    ) + 1
                    raise ValueError(f"conflicting private execution identity: {fill.exec_id}")
            document["deduplicated_replay_count"] = int(
                document.get("deduplicated_replay_count", 0)
            ) + len(replays)
            document["last_message_creation_ms"] = max(
                int(document.get("last_message_creation_ms", 0)), creation
            )
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
                    "accepted_exec_ids": accepted,
                    "deduplicated_replays": replays,
                    "version": new_version,
                }
            except VersionConflict:
                continue
        raise RuntimeError("private execution state update conflicted repeatedly")

    def snapshot(self) -> dict[str, Any]:
        current = self.database.get_json(self.namespace, self.key)
        document = _document(current["value"] if current else None, environment=self.environment)
        fills = [_fill_from_mapping(raw).to_dict() for raw in document["fills"].values()]
        fills.sort(key=lambda item: (int(item["exec_time_ms"]), item["exec_id"]))
        managed = [item for item in fills if str(item["order_link_id"]).startswith("sai_")]
        aggregates = self._aggregates(managed)
        return {
            "status": "ok",
            "environment": self.environment,
            "version": int(current["version"]) if current else 0,
            "updated_at_ms": int(document.get("updated_at_ms", 0)),
            "fills": fills,
            "managed_fills": managed,
            "managed_orders": list(aggregates.values()),
            "execution_count": len(fills),
            "managed_execution_count": len(managed),
            "deduplicated_replay_count": int(document.get("deduplicated_replay_count", 0)),
            "conflicting_duplicate_count": int(document.get("conflicting_duplicate_count", 0)),
        }

    def aggregate(self, order_link_id: str) -> dict[str, Any] | None:
        clean = _identifier(order_link_id, "orderLinkId")
        snapshot = self.snapshot()
        return next(
            (item for item in snapshot["managed_orders"] if item["order_link_id"] == clean),
            None,
        )

    def reconcile(self, order_snapshot: Mapping[str, Any]) -> dict[str, Any]:
        orders = order_snapshot.get("managed_orders") if isinstance(order_snapshot, Mapping) else None
        if not isinstance(orders, list):
            raise RuntimeError("private order snapshot must contain managed_orders")
        by_link = {
            str(item.get("order_link_id") or ""): dict(item)
            for item in orders
            if isinstance(item, Mapping) and str(item.get("order_link_id") or "")
        }
        snapshot = self.snapshot()
        aggregates = {
            str(item["order_link_id"]): item for item in snapshot["managed_orders"]
        }
        errors: list[str] = []
        orphan_execution_links = sorted(set(aggregates) - set(by_link))
        for link in orphan_execution_links:
            errors.append(f"managed execution {link} has no private order state")
        missing_execution_links: list[str] = []
        quantity_mismatch_links: list[str] = []
        for link, order in by_link.items():
            cumulative = _nonnegative(order.get("cum_exec_qty"), "cum_exec_qty")
            aggregate = aggregates.get(link)
            if cumulative > _TOLERANCE and aggregate is None:
                missing_execution_links.append(link)
                errors.append(f"executed private order {link} has no execution fills")
                continue
            if aggregate is not None and abs(float(aggregate["filled_quantity"]) - cumulative) > _TOLERANCE:
                quantity_mismatch_links.append(link)
                errors.append(f"execution quantity mismatch for {link}")
        return {
            "status": "ok" if not errors else "blocked",
            "restart_safe": not errors,
            "environment": self.environment,
            "errors": errors,
            "orphan_execution_links": orphan_execution_links,
            "missing_execution_links": missing_execution_links,
            "quantity_mismatch_links": quantity_mismatch_links,
            "conflicting_duplicate_count": snapshot["conflicting_duplicate_count"],
            "deduplicated_replay_count": snapshot["deduplicated_replay_count"],
        }

    @staticmethod
    def _aggregates(fills: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for fill in fills:
            link = str(fill["order_link_id"])
            current = result.setdefault(
                link,
                {
                    "order_link_id": link,
                    "order_id": str(fill["order_id"]),
                    "symbol": str(fill["symbol"]),
                    "category": str(fill["category"]),
                    "side": str(fill["side"]),
                    "execution_count": 0,
                    "filled_quantity": 0.0,
                    "executed_value": 0.0,
                    "actual_fee": 0.0,
                    "fee_currencies": [],
                    "maker_execution_count": 0,
                    "taker_execution_count": 0,
                    "first_exec_time_ms": int(fill["exec_time_ms"]),
                    "last_exec_time_ms": int(fill["exec_time_ms"]),
                    "exec_ids": [],
                },
            )
            if current["order_id"] and fill["order_id"] and current["order_id"] != fill["order_id"]:
                raise RuntimeError(f"orderLinkId {link} maps to multiple orderIds")
            current["execution_count"] += 1
            current["filled_quantity"] += float(fill["exec_quantity"])
            current["executed_value"] += float(fill["exec_value"])
            current["actual_fee"] += float(fill["exec_fee"])
            current["maker_execution_count"] += int(bool(fill["is_maker"]))
            current["taker_execution_count"] += int(not bool(fill["is_maker"]))
            current["first_exec_time_ms"] = min(current["first_exec_time_ms"], int(fill["exec_time_ms"]))
            current["last_exec_time_ms"] = max(current["last_exec_time_ms"], int(fill["exec_time_ms"]))
            current["exec_ids"].append(str(fill["exec_id"]))
            currency = str(fill["fee_currency"])
            if currency and currency not in current["fee_currencies"]:
                current["fee_currencies"].append(currency)
        for item in result.values():
            quantity = float(item["filled_quantity"])
            item["average_fill_price"] = (
                float(item["executed_value"]) / quantity if quantity > _TOLERANCE else 0.0
            )
            item["filled_quantity"] = round(quantity, 12)
            item["executed_value"] = round(float(item["executed_value"]), 12)
            item["actual_fee"] = round(float(item["actual_fee"]), 12)
            item["average_fill_price"] = round(float(item["average_fill_price"]), 12)
            item["exec_ids"] = sorted(item["exec_ids"])
            item["fee_currencies"] = sorted(item["fee_currencies"])
        return result


def _normalize_fill(
    row: Any,
    *,
    topic: str,
    environment: str,
    message_id: str,
    message_creation_ms: int,
    received_at_ms: int,
    max_message_lag_ms: int,
    max_future_skew_ms: int,
) -> ExecutionFill:
    if not isinstance(row, Mapping):
        raise TypeError("execution event must be an object")
    category = str(row.get("category", "")).strip().lower()
    if category not in _CATEGORIES:
        raise ValueError("invalid execution category")
    if "." in topic and topic.split(".", 1)[1] != category:
        raise ValueError("execution topic and category mismatch")
    exec_id = _identifier(row.get("execId"), "execId")
    order_id = _identifier(row.get("orderId"), "orderId")
    order_link_id = _optional_identifier(row.get("orderLinkId"), "orderLinkId")
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol or not symbol.isalnum():
        raise ValueError("invalid execution symbol")
    side = str(row.get("side", "")).strip().title()
    if side not in {"Buy", "Sell"}:
        raise ValueError("invalid execution side")
    price = _positive(row.get("execPrice"), "execPrice")
    quantity = _positive(row.get("execQty"), "execQty")
    value = _nonnegative(row.get("execValue"), "execValue")
    if value <= _TOLERANCE:
        value = price * quantity
    fee = _nonnegative(row.get("execFee"), "execFee")
    fee_rate = _finite(row.get("feeRate", 0), "feeRate")
    if abs(fee_rate) > 0.05:
        raise ValueError("feeRate is outside supported bounds")
    exec_time = _positive_int(row.get("execTime"), "execTime")
    if exec_time > received_at_ms + max_future_skew_ms:
        raise ValueError("execution timestamp is in the future")
    if exec_time > message_creation_ms + max_future_skew_ms:
        raise ValueError("execTime is ahead of creationTime")
    if received_at_ms - exec_time > max_message_lag_ms:
        raise ValueError("execution row is too old or replayed")
    sequence = int(row.get("seq") or 0)
    if sequence < 0:
        raise ValueError("execution sequence cannot be negative")
    return ExecutionFill(
        environment=environment,
        exec_id=exec_id,
        order_id=order_id,
        order_link_id=order_link_id,
        category=category,
        symbol=symbol,
        side=side,
        exec_price=price,
        exec_quantity=quantity,
        exec_value=value,
        exec_fee=fee,
        fee_rate=fee_rate,
        fee_currency=str(row.get("feeCurrency") or "").strip().upper(),
        is_maker=bool(row.get("isMaker", False)),
        exec_time_ms=exec_time,
        sequence=sequence,
        message_creation_time_ms=message_creation_ms,
        message_id=message_id,
    )


def _document(value: Any, *, environment: str) -> dict[str, Any]:
    if value is None:
        return {
            "environment": environment,
            "fills": {},
            "deduplicated_replay_count": 0,
            "conflicting_duplicate_count": 0,
            "last_message_creation_ms": 0,
            "updated_at_ms": 0,
        }
    if not isinstance(value, Mapping) or str(value.get("environment")) != environment:
        raise RuntimeError("private execution state document is invalid")
    fills = value.get("fills")
    if not isinstance(fills, Mapping):
        raise RuntimeError("private execution fills must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for key, raw in fills.items():
        if not isinstance(raw, Mapping):
            raise RuntimeError("private execution fill is invalid")
        fill = _fill_from_mapping(raw)
        if fill.exec_id != key or fill.environment != environment:
            raise RuntimeError("persisted execution identity mismatch")
        normalized[str(key)] = fill.to_dict()
    return {
        "environment": environment,
        "fills": normalized,
        "deduplicated_replay_count": int(value.get("deduplicated_replay_count", 0)),
        "conflicting_duplicate_count": int(value.get("conflicting_duplicate_count", 0)),
        "last_message_creation_ms": int(value.get("last_message_creation_ms", 0)),
        "updated_at_ms": int(value.get("updated_at_ms", 0)),
    }


def _fill_from_mapping(raw: Mapping[str, Any]) -> ExecutionFill:
    try:
        fill = ExecutionFill(**dict(raw))
    except TypeError as exc:
        raise RuntimeError("persisted execution fill is invalid") from exc
    if fill.category not in _CATEGORIES or fill.side not in {"Buy", "Sell"}:
        raise RuntimeError("persisted execution fill contains invalid enums")
    _identifier(fill.exec_id, "persisted execId")
    _identifier(fill.order_id, "persisted orderId")
    _positive(fill.exec_price, "persisted execPrice")
    _positive(fill.exec_quantity, "persisted execQty")
    _nonnegative(fill.exec_value, "persisted execValue")
    _nonnegative(fill.exec_fee, "persisted execFee")
    _positive_int(fill.exec_time_ms, "persisted execTime")
    return fill


def _environment(value: Any) -> str:
    clean = str(value).strip().lower()
    if clean in {"sandbox", "testnet"}:
        return "testnet"
    if clean in {"live", "mainnet", "live_read_only"}:
        return "mainnet"
    raise ValueError("environment must be testnet or mainnet")


def _finite(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative(value: Any, name: str) -> float:
    parsed = _finite(value or 0, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160 or not all(char.isalnum() or char in "._:-" for char in text):
        raise ValueError(f"invalid {name}")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    return _identifier(text, name) if text else ""


__all__ = ["BybitExecutionStateStore", "ExecutionFill"]
