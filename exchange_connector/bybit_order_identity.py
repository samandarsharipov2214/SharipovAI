"""Deterministic Bybit order identity and fail-closed reservation registry.

No network operations exist here. A complete supported intent maps to one stable
``orderLinkId`` and unresolved attempts block blind retries.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from storage import ProjectDatabase, VersionConflict

_ENVIRONMENTS = {"paper", "testnet", "mainnet"}
_CATEGORIES = {"spot", "linear", "inverse"}
_SIDES = {"Buy", "Sell"}
_ORDER_TYPES = {"Market", "Limit"}
_TIME_IN_FORCE = {"GTC", "IOC", "FOK", "PostOnly", "RPI"}
_MARKET_UNITS = {"baseCoin", "quoteCoin"}
_STATUSES = {
    "Reserved", "Submitted", "Untriggered", "Triggered", "New", "PartiallyFilled",
    "Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled",
}
_TERMINAL = {"Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}
_ZERO_FILL_RETRYABLE = {"Cancelled", "Rejected", "Deactivated"}
_TRANSITIONS = {
    "Reserved": _STATUSES,
    "Submitted": _STATUSES - {"Reserved"},
    "Untriggered": {"Untriggered", "Triggered", "New", "Cancelled", "Rejected", "Deactivated"},
    "Triggered": {"Triggered", "New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "Deactivated"},
    "New": {"New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled", "PartiallyFilledCanceled"},
}


@dataclass(frozen=True, slots=True)
class OrderIntent:
    candidate_id: str
    environment: str
    category: str
    symbol: str
    side: str
    order_type: str
    quantity: str
    price: str
    time_in_force: str
    reduce_only: bool
    position_idx: int
    market_unit: str
    attempt: int = 1

    @classmethod
    def create(
        cls,
        *,
        candidate_id: Any,
        environment: Any,
        category: Any,
        symbol: Any,
        side: Any,
        order_type: Any,
        quantity: Any,
        price: Any = None,
        time_in_force: Any = None,
        reduce_only: Any = False,
        position_idx: Any = 0,
        market_unit: Any = None,
        attempt: Any = 1,
    ) -> "OrderIntent":
        candidate = _identifier(candidate_id, "candidate_id")
        env = _choice(environment, "environment", _ENVIRONMENTS, lower=True)
        category_value = _choice(category, "category", _CATEGORIES, lower=True)
        side_value = _choice(side, "side", _SIDES, title=True)
        order_type_value = _choice(order_type, "order_type", _ORDER_TYPES, title=True)
        symbol_value = str(symbol).strip().upper().replace("/", "").replace("-", "")
        if not symbol_value or not symbol_value.isalnum():
            raise ValueError("invalid symbol")
        quantity_value = _decimal(quantity, "quantity", positive=True)
        price_value = _decimal(price, "price", positive=True) if price not in {None, ""} else ""
        attempt_value = _positive_int(attempt, "attempt")
        position_value = int(position_idx)
        if position_value not in {0, 1, 2}:
            raise ValueError("position_idx must be 0, 1 or 2")
        if not isinstance(reduce_only, bool):
            raise TypeError("reduce_only must be boolean")

        if order_type_value == "Market":
            if price_value:
                raise ValueError("market order must not contain price")
            tif = "IOC" if time_in_force in {None, ""} else _choice(time_in_force, "time_in_force", _TIME_IN_FORCE)
            if tif != "IOC":
                raise ValueError("market order requires IOC")
        else:
            if not price_value:
                raise ValueError("limit order requires price")
            tif = "GTC" if time_in_force in {None, ""} else _choice(time_in_force, "time_in_force", _TIME_IN_FORCE)

        unit = str(market_unit or "").strip()
        if category_value == "spot" and order_type_value == "Market":
            unit = unit or ("quoteCoin" if side_value == "Buy" else "baseCoin")
            if unit not in _MARKET_UNITS:
                raise ValueError("invalid spot marketUnit")
        elif unit:
            raise ValueError("market_unit is allowed only for spot market orders")
        if category_value == "spot" and (reduce_only or position_value != 0):
            raise ValueError("spot orders cannot use reduce_only or position_idx")

        return cls(
            candidate_id=candidate,
            environment=env,
            category=category_value,
            symbol=symbol_value,
            side=side_value,
            order_type=order_type_value,
            quantity=quantity_value,
            price=price_value,
            time_in_force=tif,
            reduce_only=reduce_only,
            position_idx=position_value,
            market_unit=unit,
            attempt=attempt_value,
        )

    def root_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("attempt")
        return data

    def root_fingerprint(self) -> str:
        return _digest(self.root_payload())

    def fingerprint(self) -> str:
        return _digest(asdict(self))

    def order_link_id(self) -> str:
        return f"sai_{self.fingerprint()[:32]}"


class OrderIntentRegistry:
    """Persist reservations and exchange identity in the canonical database."""

    def __init__(self, *, database: ProjectDatabase | None = None, environment: str = "testnet") -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.environment = _choice(environment, "environment", _ENVIRONMENTS, lower=True)
        self.namespace = "bybit_order_identity"
        self.key = self.environment

    def reserve(self, intent: OrderIntent, *, created_at_ms: int | None = None) -> dict[str, Any]:
        if intent.environment != self.environment:
            raise ValueError("intent environment does not match registry")
        now = _timestamp(created_at_ms)
        full = intent.fingerprint()
        root = intent.root_fingerprint()
        link = intent.order_link_id()

        def mutate(document: dict[str, Any]) -> dict[str, Any]:
            reservations = document["reservations"]
            fingerprints = document["fingerprints"]
            existing_link = fingerprints.get(full)
            if existing_link:
                existing = reservations.get(existing_link)
                if not isinstance(existing, dict):
                    raise RuntimeError("identity registry fingerprint is corrupt")
                return {"document": document, "result": {**existing, "duplicate": True, "requires_reconciliation": True}}
            if link in reservations:
                raise RuntimeError("deterministic orderLinkId collision")
            previous = [
                item for item in reservations.values()
                if isinstance(item, dict) and item.get("root_fingerprint") == root
            ]
            if intent.attempt == 1:
                if previous:
                    raise RuntimeError("first attempt already exists for this order intent")
            else:
                if not previous:
                    raise RuntimeError("retry attempt has no previous reservation")
                latest = max(previous, key=lambda item: int(item.get("attempt", 0)))
                if intent.attempt != int(latest.get("attempt", 0)) + 1:
                    raise RuntimeError("retry attempt must be sequential")
                if latest.get("status") not in _ZERO_FILL_RETRYABLE or float(latest.get("cum_exec_qty", 0)) != 0:
                    raise RuntimeError("previous attempt is unresolved or executed; retry is blocked")
            record = {
                "order_link_id": link,
                "order_id": "",
                "fingerprint": full,
                "root_fingerprint": root,
                "intent": asdict(intent),
                "attempt": intent.attempt,
                "status": "Reserved",
                "cum_exec_qty": 0.0,
                "created_at_ms": now,
                "updated_at_ms": now,
                "revision": 1,
            }
            reservations[link] = record
            fingerprints[full] = link
            document["updated_at_ms"] = now
            return {"document": document, "result": {**record, "duplicate": False, "requires_reconciliation": False}}

        return self._update(mutate)

    def bind_submission(self, order_link_id: str, *, order_id: Any, updated_at_ms: int | None = None) -> dict[str, Any]:
        link = _order_link(order_link_id)
        exchange_id = _identifier(order_id, "order_id")
        now = _timestamp(updated_at_ms)

        def mutate(document: dict[str, Any]) -> dict[str, Any]:
            reservations = document["reservations"]
            record = _record(reservations, link)
            for other_link, other in reservations.items():
                if other_link != link and isinstance(other, dict) and other.get("order_id") == exchange_id:
                    raise RuntimeError("exchange orderId is already bound to another reservation")
            existing_id = str(record.get("order_id", ""))
            if existing_id and existing_id != exchange_id:
                raise RuntimeError("reservation is already bound to another orderId")
            if now < int(record["updated_at_ms"]):
                raise ValueError("updated_at_ms regression")
            status = str(record["status"])
            if status == "Reserved":
                status = "Submitted"
            updated = {**record, "order_id": exchange_id, "status": status, "updated_at_ms": now, "revision": int(record["revision"]) + 1}
            reservations[link] = updated
            document["updated_at_ms"] = now
            return {"document": document, "result": updated}

        return self._update(mutate)

    def update_status(
        self,
        order_link_id: str,
        *,
        status: str,
        cum_exec_qty: Any,
        updated_at_ms: int | None = None,
        order_id: Any | None = None,
    ) -> dict[str, Any]:
        link = _order_link(order_link_id)
        status_value = str(status).strip()
        if status_value not in _STATUSES:
            raise ValueError("unsupported order status")
        executed = _number(cum_exec_qty, "cum_exec_qty")
        if executed < 0:
            raise ValueError("cum_exec_qty must not be negative")
        now = _timestamp(updated_at_ms)
        exchange_id = _identifier(order_id, "order_id") if order_id not in {None, ""} else ""

        def mutate(document: dict[str, Any]) -> dict[str, Any]:
            reservations = document["reservations"]
            record = _record(reservations, link)
            old_status = str(record["status"])
            old_exec = float(record["cum_exec_qty"])
            old_time = int(record["updated_at_ms"])
            if now < old_time:
                raise ValueError("updated_at_ms regression")
            if executed < old_exec:
                raise ValueError("cum_exec_qty regression")
            if old_status in _TERMINAL and (status_value != old_status or executed != old_exec):
                raise ValueError("terminal reservation cannot change")
            if old_status not in _TERMINAL and status_value not in _TRANSITIONS.get(old_status, {old_status}):
                raise ValueError(f"invalid transition {old_status}->{status_value}")
            bound_id = str(record.get("order_id", ""))
            if exchange_id and bound_id and exchange_id != bound_id:
                raise RuntimeError("orderId mismatch")
            if exchange_id:
                for other_link, other in reservations.items():
                    if other_link != link and isinstance(other, dict) and other.get("order_id") == exchange_id:
                        raise RuntimeError("exchange orderId is already bound")
            updated = {
                **record,
                "order_id": exchange_id or bound_id,
                "status": status_value,
                "cum_exec_qty": executed,
                "updated_at_ms": now,
                "revision": int(record["revision"]) + 1,
            }
            reservations[link] = updated
            document["updated_at_ms"] = now
            return {"document": document, "result": updated}

        return self._update(mutate)

    def snapshot(self) -> dict[str, Any]:
        current = self.database.get_json(self.namespace, self.key)
        document = _document(current["value"] if current else None, environment=self.environment)
        records = list(document["reservations"].values())
        records.sort(key=lambda item: (int(item["created_at_ms"]), item["order_link_id"]))
        unresolved = [item for item in records if item["status"] not in _TERMINAL]
        return {
            "status": "ok",
            "environment": self.environment,
            "version": int(current["version"]) if current else 0,
            "reservations": records,
            "unresolved": unresolved,
            "restart_safe": not unresolved,
        }

    def _update(self, mutation: Any) -> dict[str, Any]:
        for _attempt in range(5):
            current = self.database.get_json(self.namespace, self.key)
            version = int(current["version"]) if current else 0
            document = _document(current["value"] if current else None, environment=self.environment)
            outcome = mutation(document)
            try:
                self.database.put_json(self.namespace, self.key, outcome["document"], expected_version=version)
                return dict(outcome["result"])
            except VersionConflict:
                continue
        raise RuntimeError("order identity update conflicted repeatedly")


def _document(value: Any, *, environment: str) -> dict[str, Any]:
    if value is None:
        return {"environment": environment, "reservations": {}, "fingerprints": {}, "updated_at_ms": 0}
    if not isinstance(value, dict) or value.get("environment") != environment:
        raise RuntimeError("identity registry document is invalid")
    reservations = value.get("reservations")
    fingerprints = value.get("fingerprints")
    if not isinstance(reservations, dict) or not isinstance(fingerprints, dict):
        raise RuntimeError("identity registry structure is invalid")
    expected: dict[str, str] = {}
    order_ids: set[str] = set()
    for link, raw in reservations.items():
        if _order_link(link) != link or not isinstance(raw, dict):
            raise RuntimeError("identity reservation is invalid")
        intent_raw = raw.get("intent")
        if not isinstance(intent_raw, dict):
            raise RuntimeError("identity intent is missing")
        intent = OrderIntent.create(**intent_raw)
        if intent.environment != environment or intent.order_link_id() != link:
            raise RuntimeError("persisted identity does not match intent")
        if raw.get("fingerprint") != intent.fingerprint() or raw.get("root_fingerprint") != intent.root_fingerprint():
            raise RuntimeError("persisted identity fingerprint mismatch")
        status = str(raw.get("status", ""))
        if status not in _STATUSES:
            raise RuntimeError("persisted identity status is invalid")
        executed = _number(raw.get("cum_exec_qty", 0), "persisted cum_exec_qty")
        if executed < 0:
            raise RuntimeError("persisted execution quantity is invalid")
        _positive_int(raw.get("attempt"), "persisted attempt")
        _positive_int(raw.get("revision"), "persisted revision")
        _timestamp(raw.get("created_at_ms"))
        _timestamp(raw.get("updated_at_ms"))
        order_id = str(raw.get("order_id", ""))
        if order_id:
            _identifier(order_id, "persisted order_id")
            if order_id in order_ids:
                raise RuntimeError("persisted orderId collision")
            order_ids.add(order_id)
        expected[intent.fingerprint()] = link
    if fingerprints != expected:
        raise RuntimeError("persisted fingerprint index mismatch")
    return {
        "environment": environment,
        "reservations": {str(key): dict(value) for key, value in reservations.items()},
        "fingerprints": dict(fingerprints),
        "updated_at_ms": int(value.get("updated_at_ms", 0)),
    }


def _record(reservations: dict[str, Any], link: str) -> dict[str, Any]:
    record = reservations.get(link)
    if not isinstance(record, dict):
        raise KeyError(f"unknown orderLinkId: {link}")
    return record


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: Any, name: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 128 or not all(char.isalnum() or char in "._:-" for char in text):
        raise ValueError(f"invalid {name}")
    return text


def _order_link(value: Any) -> str:
    text = str(value).strip()
    if not text.startswith("sai_") or len(text) > 36 or not all(char.isalnum() or char in "_-" for char in text):
        raise ValueError("invalid SharipovAI orderLinkId")
    return text


def _choice(value: Any, name: str, choices: set[str], *, lower: bool = False, title: bool = False) -> str:
    text = str(value).strip()
    if lower:
        text = text.lower()
    elif title:
        text = text.title()
    if text not in choices:
        raise ValueError(f"invalid {name}")
    return text


def _decimal(value: Any, name: str, *, positive: bool = False) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"invalid {name}")
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _number(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


__all__ = ["OrderIntent", "OrderIntentRegistry"]
