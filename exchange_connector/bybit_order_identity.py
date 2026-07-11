"""Deterministic Bybit orderLinkId and fail-closed submission reservations.

This module never places orders. It creates a stable client order identity for one
business intent and prevents a retry from silently becoming a second order.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_LINK_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_ALLOWED_ENVIRONMENTS = {"paper", "testnet", "mainnet"}
_ALLOWED_CATEGORIES = {"spot", "linear", "inverse", "option"}
_ALLOWED_SIDES = {"Buy", "Sell"}
_TERMINAL_STATUSES = {"Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}


@dataclass(frozen=True, slots=True)
class OrderIntent:
    candidate_id: str
    environment: str
    category: str
    symbol: str
    side: str
    quantity: str
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
        quantity: Any,
        attempt: Any = 1,
    ) -> "OrderIntent":
        return cls(
            candidate_id=_identifier(candidate_id, "candidate_id"),
            environment=_choice(environment, "environment", _ALLOWED_ENVIRONMENTS, lower=True),
            category=_choice(category, "category", _ALLOWED_CATEGORIES, lower=True),
            symbol=_symbol(symbol),
            side=_choice(str(side).strip().title(), "side", _ALLOWED_SIDES),
            quantity=_decimal_text(quantity, "quantity"),
            attempt=_positive_int(attempt, "attempt"),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def order_link_id(self) -> str:
        return build_order_link_id(self)


def build_order_link_id(intent: OrderIntent) -> str:
    """Return a deterministic Bybit-compatible ID no longer than 36 characters."""
    env = {"paper": "p", "testnet": "t", "mainnet": "m"}[intent.environment]
    category = {"spot": "s", "linear": "l", "inverse": "i", "option": "o"}[intent.category]
    digest = hashlib.blake2s(intent.fingerprint.encode(), digest_size=14).hexdigest()
    value = f"sai_{env}{category}_{digest}"
    if len(value) > 36 or not _LINK_PATTERN.fullmatch(value):
        raise RuntimeError("generated orderLinkId violates Bybit format")
    return value


class OrderIntentRegistry:
    """Persist submission reservations so retries reconcile instead of resubmit."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("BYBIT_ORDER_INTENT_FILE", "data/bybit_order_intents.json"))
        self._lock = threading.RLock()

    def reserve(self, intent: OrderIntent, *, now_ms: int | None = None) -> dict[str, Any]:
        current_ms = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        link_id = intent.order_link_id
        with self._lock:
            document = self._load_document()
            records = dict(document.get("records", {}))
            existing = records.get(link_id)
            if existing is not None:
                if not isinstance(existing, Mapping):
                    raise RuntimeError("persisted order intent is invalid")
                if str(existing.get("fingerprint", "")) != intent.fingerprint:
                    return {
                        "status": "blocked",
                        "safe_to_submit": False,
                        "must_reconcile": True,
                        "reason": "orderLinkId collision with a different intent",
                        "order_link_id": link_id,
                        "record": dict(existing),
                    }
                return {
                    "status": "duplicate",
                    "safe_to_submit": False,
                    "must_reconcile": True,
                    "reason": "intent already reserved; query private order state before retry",
                    "order_link_id": link_id,
                    "record": dict(existing),
                }

            record = {
                "order_link_id": link_id,
                "fingerprint": intent.fingerprint,
                "intent": intent.canonical_payload(),
                "status": "reserved",
                "exchange_order_id": "",
                "reserved_at_ms": current_ms,
                "updated_at_ms": current_ms,
            }
            records[link_id] = record
            self._write_document({"records": records, "updated_at_ms": current_ms})
            return {
                "status": "reserved",
                "safe_to_submit": True,
                "must_reconcile": False,
                "reason": "new intent reservation",
                "order_link_id": link_id,
                "record": dict(record),
            }

    def bind_exchange_order(
        self,
        order_link_id: str,
        order_id: str,
        *,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        link_id = _link_id(order_link_id)
        exchange_id = _identifier(order_id, "order_id")
        current_ms = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        with self._lock:
            document = self._load_document()
            records = dict(document.get("records", {}))
            raw = records.get(link_id)
            if not isinstance(raw, Mapping):
                raise KeyError("orderLinkId reservation not found")
            record = dict(raw)
            existing_order_id = str(record.get("exchange_order_id", ""))
            if existing_order_id and existing_order_id != exchange_id:
                raise RuntimeError("reservation is already bound to another Bybit orderId")
            record["exchange_order_id"] = exchange_id
            record["status"] = "accepted"
            record["updated_at_ms"] = current_ms
            records[link_id] = record
            self._write_document({"records": records, "updated_at_ms": current_ms})
            return dict(record)

    def update_status(self, order_link_id: str, status: str, *, now_ms: int | None = None) -> dict[str, Any]:
        link_id = _link_id(order_link_id)
        clean_status = str(status).strip()
        if not clean_status:
            raise ValueError("status is required")
        current_ms = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        with self._lock:
            document = self._load_document()
            records = dict(document.get("records", {}))
            raw = records.get(link_id)
            if not isinstance(raw, Mapping):
                raise KeyError("orderLinkId reservation not found")
            record = dict(raw)
            previous = str(record.get("status", ""))
            if previous in _TERMINAL_STATUSES and previous != clean_status:
                raise RuntimeError("terminal intent status cannot transition")
            record["status"] = clean_status
            record["updated_at_ms"] = current_ms
            records[link_id] = record
            self._write_document({"records": records, "updated_at_ms": current_ms})
            return dict(record)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            document = self._load_document()
        records = document.get("records", {})
        values = [dict(item) for item in records.values() if isinstance(item, Mapping)]
        unresolved = [item for item in values if str(item.get("status", "")) not in _TERMINAL_STATUSES]
        return {
            "status": "ok",
            "tracked_intents": len(values),
            "unresolved_intents": unresolved,
            "restart_safe": not unresolved,
            "records": values,
            "updated_at_ms": document.get("updated_at_ms"),
        }

    def _load_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"records": {}, "updated_at_ms": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"order intent file is unreadable: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("records", {}), dict):
            raise RuntimeError("order intent file has invalid structure")
        return data

    def _write_document(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


def _identifier(value: Any, name: str) -> str:
    text = str(value).strip()
    if not _ID_PATTERN.fullmatch(text):
        raise ValueError(f"{name} has invalid format")
    return text


def _link_id(value: Any) -> str:
    text = str(value).strip()
    if not _LINK_PATTERN.fullmatch(text):
        raise ValueError("orderLinkId has invalid format")
    return text


def _symbol(value: Any) -> str:
    text = str(value).strip().upper().replace("/", "").replace("-", "")
    if not text or len(text) > 30 or not text.isalnum():
        raise ValueError("symbol has invalid format")
    return text


def _choice(value: Any, name: str, allowed: set[str], *, lower: bool = False) -> str:
    text = str(value).strip()
    if lower:
        text = text.lower()
    if text not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return text


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


def _decimal_text(value: Any, name: str) -> str:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a positive number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TypeError(f"{name} must be a positive number") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    normalized = format(parsed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized
