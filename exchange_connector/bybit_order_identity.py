"""Deterministic Bybit order identity and fail-closed reservation registry.

This module does not perform network calls. It guarantees that one supported,
complete order intent maps to one stable orderLinkId and that retries reconcile
instead of silently creating duplicate orders.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_LINK_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_ENVIRONMENTS = {"paper", "testnet", "mainnet"}
_CATEGORIES = {"spot", "linear", "inverse"}
_SIDES = {"Buy", "Sell"}
_ORDER_TYPES = {"Market", "Limit"}
_TIME_IN_FORCE = {"GTC", "IOC", "FOK", "PostOnly", "RPI"}
_MARKET_UNITS = {"baseCoin", "quoteCoin"}
_ALLOWED_STATUSES = {
    "Reserved", "Submitted", "Untriggered", "Triggered", "New", "PartiallyFilled",
    "Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled",
}
_TERMINAL = {"Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled"}
_TRANSITIONS = {
    "Reserved": {
        "Reserved", "Submitted", "Untriggered", "Triggered", "New", "PartiallyFilled",
        "Filled", "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled",
    },
    "Submitted": {
        "Submitted", "Untriggered", "Triggered", "New", "PartiallyFilled", "Filled",
        "Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled",
    },
    "Untriggered": {"Untriggered", "Triggered", "New", "Cancelled", "Rejected", "Deactivated"},
    "Triggered": {"Triggered", "New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "Deactivated"},
    "New": {"New", "PartiallyFilled", "Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled", "PartiallyFilledCanceled"},
}
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_LOCK_TIMEOUT_SECONDS = 10.0
_STALE_LOCK_SECONDS = 60.0


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
    trigger_price: str
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
        trigger_price: Any = None,
        time_in_force: Any = None,
        reduce_only: Any = False,
        position_idx: Any = 0,
        market_unit: Any = None,
        attempt: Any = 1,
    ) -> "OrderIntent":
        clean_environment = _required_choice(environment, "environment", _ENVIRONMENTS, transform="lower")
        clean_category = _required_choice(category, "category", _CATEGORIES, transform="lower")
        clean_side = _required_choice(side, "side", _SIDES, transform="title")
        clean_type = _required_choice(order_type, "order_type", _ORDER_TYPES, transform="title")
        clean_price = _optional_decimal(price, "price")
        clean_trigger = _optional_decimal(trigger_price, "trigger_price")
        if clean_trigger:
            raise ValueError("conditional orders are not supported by this identity contract")

        if clean_type == "Limit":
            if not clean_price:
                raise ValueError("Limit order requires price")
            tif = _required_choice(time_in_force or "GTC", "time_in_force", _TIME_IN_FORCE)
        else:
            if clean_price:
                raise ValueError("Market order must not include price")
            tif = _required_text(time_in_force or "IOC", "time_in_force")
            if tif != "IOC":
                raise ValueError("Market order time_in_force must be IOC")

        clean_reduce_only = _boolean(reduce_only, "reduce_only")
        clean_position_idx = _position_idx(position_idx)
        requested_unit = "" if market_unit is None else _optional_text(market_unit, "market_unit")
        if clean_category == "spot":
            if clean_reduce_only:
                raise ValueError("spot orders cannot use reduce_only")
            if clean_position_idx != 0:
                raise ValueError("spot orders require position_idx=0")
            if clean_type == "Market":
                clean_unit = requested_unit or ("quoteCoin" if clean_side == "Buy" else "baseCoin")
                clean_unit = _required_choice(clean_unit, "market_unit", _MARKET_UNITS)
            else:
                if requested_unit:
                    raise ValueError("spot Limit orders must not include market_unit")
                clean_unit = ""
        else:
            if requested_unit:
                raise ValueError("market_unit is valid only for spot Market orders")
            clean_unit = ""

        return cls(
            candidate_id=_identifier(candidate_id, "candidate_id"),
            environment=clean_environment,
            category=clean_category,
            symbol=_symbol(symbol),
            side=clean_side,
            order_type=clean_type,
            quantity=_decimal(quantity, "quantity", positive=True),
            price=clean_price,
            trigger_price="",
            time_in_force=tif,
            reduce_only=clean_reduce_only,
            position_idx=clean_position_idx,
            market_unit=clean_unit,
            attempt=_positive_int(attempt, "attempt"),
        )

    def canonical_payload(self, *, include_attempt: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if not include_attempt:
            payload.pop("attempt")
        return payload

    @property
    def root_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload(include_attempt=False))

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def order_link_id(self) -> str:
        prefix = {"paper": "p", "testnet": "t", "mainnet": "m"}[self.environment]
        category = {"spot": "s", "linear": "l", "inverse": "i"}[self.category]
        digest = hashlib.blake2s(self.fingerprint.encode(), digest_size=14).hexdigest()
        value = f"sai_{prefix}{category}_{digest}"
        if not _LINK_RE.fullmatch(value):
            raise RuntimeError("generated orderLinkId violates Bybit format")
        return value

    @property
    def execution_unit(self) -> str:
        if self.category == "spot" and self.order_type == "Market" and self.market_unit == "quoteCoin":
            return "quoteCoin"
        return "baseCoin"


class OrderIntentRegistry:
    """Persist reservations before POST and require reconciliation for retries."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("BYBIT_ORDER_INTENT_FILE", "data/bybit_order_intents.json"))
        self._thread_lock = _shared_path_lock(self.path)

    def reserve(self, intent: OrderIntent, *, now_ms: int | None = None) -> dict[str, Any]:
        if not isinstance(intent, OrderIntent):
            raise TypeError("intent must be an OrderIntent")
        current = _positive_int(now_ms if now_ms is not None else int(time.time() * 1000), "now_ms")
        link_id = intent.order_link_id
        with self._transaction():
            document = self._load()
            records = dict(document["records"])
            existing = records.get(link_id)
            if existing is not None:
                if not isinstance(existing, Mapping) or str(existing.get("fingerprint", "")) != intent.fingerprint:
                    raise RuntimeError("orderLinkId collision or corrupt reservation")
                return {
                    "status": "duplicate", "safe_to_submit": False, "must_reconcile": True,
                    "order_link_id": link_id, "record": dict(existing),
                }
            if intent.attempt > 1:
                previous = _previous_attempt(records, intent)
                if previous is None or not _retry_safe(previous):
                    return {
                        "status": "blocked", "safe_to_submit": False, "must_reconcile": True,
                        "reason": "previous attempt is not proven terminal without execution",
                        "order_link_id": link_id,
                    }
            record = {
                "order_link_id": link_id,
                "fingerprint": intent.fingerprint,
                "root_fingerprint": intent.root_fingerprint,
                "intent": intent.canonical_payload(),
                "status": "Reserved",
                "exchange_order_id": "",
                "cum_exec_qty": "0",
                "cum_exec_value": "0",
                "reserved_at_ms": current,
                "updated_at_ms": current,
                "revision": 1,
            }
            records[link_id] = record
            self._write({"records": records, "updated_at_ms": current})
            return {
                "status": "reserved", "safe_to_submit": True, "must_reconcile": False,
                "order_link_id": link_id, "record": dict(record),
            }

    def bind_exchange_order(self, order_link_id: Any, order_id: Any, *, now_ms: int | None = None) -> dict[str, Any]:
        link_id = _link(order_link_id)
        exchange_id = _identifier(order_id, "order_id")
        current = _positive_int(now_ms if now_ms is not None else int(time.time() * 1000), "now_ms")
        with self._transaction():
            document = self._load()
            records = dict(document["records"])
            raw = records.get(link_id)
            if not isinstance(raw, Mapping):
                raise KeyError("orderLinkId reservation not found")
            for other_link, other_raw in records.items():
                if other_link != link_id and isinstance(other_raw, Mapping) and str(other_raw.get("exchange_order_id", "")) == exchange_id:
                    raise RuntimeError("orderId is already bound to another reservation")
            record = dict(raw)
            previous_updated = _positive_int(record.get("updated_at_ms"), "persisted updated_at_ms")
            if current < previous_updated:
                raise RuntimeError("status update timestamp regressed")
            existing_exchange_id = str(record.get("exchange_order_id", ""))
            if existing_exchange_id and existing_exchange_id != exchange_id:
                raise RuntimeError("reservation is already bound to another orderId")
            changed = not existing_exchange_id
            record["exchange_order_id"] = exchange_id
            if str(record.get("status")) == "Reserved":
                record["status"] = "Submitted"
                changed = True
            record["updated_at_ms"] = max(current, previous_updated)
            if changed:
                record["revision"] = _positive_int(record.get("revision", 1), "persisted revision") + 1
            records[link_id] = record
            self._write({"records": records, "updated_at_ms": record["updated_at_ms"]})
            return dict(record)

    def update_status(
        self,
        order_link_id: Any,
        status: Any,
        *,
        cum_exec_qty: Any | None = None,
        cum_exec_value: Any | None = None,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        link_id = _link(order_link_id)
        clean_status = _required_choice(status, "status", _ALLOWED_STATUSES)
        current = _positive_int(now_ms if now_ms is not None else int(time.time() * 1000), "now_ms")
        with self._transaction():
            document = self._load()
            records = dict(document["records"])
            raw = records.get(link_id)
            if not isinstance(raw, Mapping):
                raise KeyError("orderLinkId reservation not found")
            record = dict(raw)
            intent = _intent_from_record(record)
            previous_status = str(record.get("status", ""))
            previous_updated = _positive_int(record.get("updated_at_ms"), "persisted updated_at_ms")
            if current < previous_updated:
                raise RuntimeError("status update timestamp regressed")
            previous_qty = _decimal_value(record.get("cum_exec_qty", "0"), "persisted cum_exec_qty")
            previous_value = _decimal_value(record.get("cum_exec_value", "0"), "persisted cum_exec_value")
            next_qty = previous_qty if cum_exec_qty is None else _decimal_value(cum_exec_qty, "cum_exec_qty")
            next_value = previous_value if cum_exec_value is None else _decimal_value(cum_exec_value, "cum_exec_value")
            if next_qty < previous_qty or next_value < previous_value:
                raise RuntimeError("executed quantity or value regressed")
            if previous_status in _TERMINAL:
                if clean_status != previous_status:
                    raise RuntimeError("terminal reservation cannot transition")
                if next_qty != previous_qty or next_value != previous_value:
                    raise RuntimeError("terminal reservation execution cannot change")
            _validate_execution(clean_status, intent, next_qty, next_value)
            if clean_status not in _TRANSITIONS.get(previous_status, {previous_status}):
                raise RuntimeError(f"invalid status transition {previous_status}->{clean_status}")
            changed = clean_status != previous_status or next_qty != previous_qty or next_value != previous_value
            record["status"] = clean_status
            record["cum_exec_qty"] = _canonical_decimal(next_qty)
            record["cum_exec_value"] = _canonical_decimal(next_value)
            record["updated_at_ms"] = max(current, previous_updated)
            if changed:
                record["revision"] = _positive_int(record.get("revision", 1), "persisted revision") + 1
            records[link_id] = record
            self._write({"records": records, "updated_at_ms": record["updated_at_ms"]})
            return dict(record)

    def snapshot(self) -> dict[str, Any]:
        with self._transaction():
            document = self._load()
        values = [dict(value) for value in document["records"].values()]
        unresolved = [value for value in values if str(value.get("status", "")) not in _TERMINAL]
        return {
            "status": "ok", "tracked_intents": len(values), "unresolved_intents": unresolved,
            "restart_safe": not unresolved, "records": values, "updated_at_ms": document.get("updated_at_ms"),
        }

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            with _exclusive_lock_file(self.path):
                yield

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"records": {}, "updated_at_ms": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"order intent file is unreadable: {type(exc).__name__}") from exc
        _validate_document(data)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        _validate_document(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def _shared_path_lock(path: Path) -> threading.RLock:
    key = str(path.expanduser().resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _exclusive_lock_file(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()}\n{time.time()}".encode())
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > _STALE_LOCK_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError("timed out waiting for order intent registry lock")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _previous_attempt(records: Mapping[str, Any], intent: OrderIntent) -> Mapping[str, Any] | None:
    target_attempt = intent.attempt - 1
    matches = []
    for raw in records.values():
        if not isinstance(raw, Mapping) or str(raw.get("root_fingerprint", "")) != intent.root_fingerprint:
            continue
        payload = raw.get("intent")
        if isinstance(payload, Mapping) and _nonnegative_int(payload.get("attempt", 0), "persisted attempt") == target_attempt:
            matches.append(raw)
    if len(matches) > 1:
        raise RuntimeError("multiple previous-attempt reservations found")
    return matches[0] if matches else None


def _retry_safe(record: Mapping[str, Any]) -> bool:
    status = str(record.get("status", ""))
    cum_qty = _decimal_value(record.get("cum_exec_qty", "0"), "persisted cum_exec_qty")
    cum_value = _decimal_value(record.get("cum_exec_value", "0"), "persisted cum_exec_value")
    return status in {"Rejected", "Deactivated", "Cancelled"} and cum_qty == 0 and cum_value == 0


def _validate_document(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
        raise RuntimeError("order intent file has invalid structure")
    if data.get("updated_at_ms") is not None:
        _positive_int(data.get("updated_at_ms"), "persisted updated_at_ms")
    bound_order_ids: dict[str, str] = {}
    for link_id, raw in data["records"].items():
        try:
            clean_link = _link(link_id)
        except ValueError as exc:
            raise RuntimeError("order intent file contains an invalid orderLinkId") from exc
        if not isinstance(raw, Mapping):
            raise RuntimeError("order intent file contains invalid records")
        record = dict(raw)
        if str(record.get("order_link_id", "")) != clean_link:
            raise RuntimeError("persisted orderLinkId mismatch")
        intent = _intent_from_record(record)
        if intent.order_link_id != clean_link:
            raise RuntimeError("persisted intent does not match orderLinkId")
        if str(record.get("fingerprint", "")) != intent.fingerprint:
            raise RuntimeError("persisted intent fingerprint mismatch")
        if str(record.get("root_fingerprint", "")) != intent.root_fingerprint:
            raise RuntimeError("persisted intent root fingerprint mismatch")
        status = str(record.get("status", ""))
        if status not in _ALLOWED_STATUSES:
            raise RuntimeError("persisted reservation status is invalid")
        reserved_at = _positive_int(record.get("reserved_at_ms"), "persisted reserved_at_ms")
        updated_at = _positive_int(record.get("updated_at_ms"), "persisted updated_at_ms")
        _positive_int(record.get("revision", 1), "persisted revision")
        if updated_at < reserved_at:
            raise RuntimeError("persisted reservation timestamp regressed")
        cum_qty = _decimal_value(record.get("cum_exec_qty", "0"), "persisted cum_exec_qty")
        cum_value = _decimal_value(record.get("cum_exec_value", "0"), "persisted cum_exec_value")
        try:
            _validate_execution(status, intent, cum_qty, cum_value)
        except ValueError as exc:
            raise RuntimeError(f"persisted execution state is inconsistent: {exc}") from exc
        exchange_id = record.get("exchange_order_id", "")
        if exchange_id not in {"", None}:
            try:
                clean_exchange_id = _identifier(exchange_id, "exchange_order_id")
            except ValueError as exc:
                raise RuntimeError("persisted exchange_order_id is invalid") from exc
            existing = bound_order_ids.get(clean_exchange_id)
            if existing and existing != clean_link:
                raise RuntimeError("one exchange orderId is bound to multiple reservations")
            bound_order_ids[clean_exchange_id] = clean_link
        elif status == "Submitted":
            raise RuntimeError("Submitted reservation lacks exchange_order_id")


def _intent_from_record(record: Mapping[str, Any]) -> OrderIntent:
    payload = record.get("intent")
    if not isinstance(payload, Mapping):
        raise RuntimeError("persisted intent payload is invalid")
    try:
        return OrderIntent.create(**dict(payload))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"persisted intent payload is invalid: {exc}") from exc


def _execution_progress(intent: OrderIntent, cum_qty: Decimal, cum_value: Decimal) -> Decimal:
    return cum_value if intent.execution_unit == "quoteCoin" else cum_qty


def _validate_execution(status: str, intent: OrderIntent, cum_qty: Decimal, cum_value: Decimal) -> None:
    if cum_qty < 0 or cum_value < 0:
        raise ValueError("executed quantity and value must not be negative")
    target = Decimal(intent.quantity)
    progress = _execution_progress(intent, cum_qty, cum_value)
    if progress > target:
        raise ValueError("executed progress exceeds order quantity")
    if progress > 0 and cum_qty <= 0:
        raise ValueError("executed base quantity is required after execution")
    if status == "Filled" and progress != target:
        raise ValueError("Filled requires full executed progress in the intent unit")
    if status == "PartiallyFilled" and not (Decimal("0") < progress < target):
        raise ValueError("PartiallyFilled requires partial executed progress")
    if status == "PartiallyFilledCanceled":
        if intent.category != "spot":
            raise ValueError("PartiallyFilledCanceled is valid only for spot orders")
        if not (Decimal("0") < progress < target):
            raise ValueError("PartiallyFilledCanceled requires partial executed progress")
    if status == "Cancelled":
        if progress >= target:
            raise ValueError("Cancelled cannot report full executed progress")
        if intent.category == "spot" and progress > 0:
            raise ValueError("partially filled spot cancellation requires PartiallyFilledCanceled")
    if status in {"Reserved", "Submitted", "Untriggered", "Triggered", "New", "Rejected", "Deactivated"}:
        if cum_qty != 0 or cum_value != 0:
            raise ValueError(f"{status} cannot report executed quantity or value")


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _required_text(value: Any, name: str) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} is required")
    text = str(value).strip()
    if not text or text.casefold() in {"none", "null"}:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: Any, name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be text")
    return str(value).strip()


def _required_choice(value: Any, name: str, allowed: set[str], *, transform: str | None = None) -> str:
    text = _required_text(value, name)
    if transform == "lower":
        text = text.lower()
    elif transform == "title":
        text = text.title()
    if text not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return text


def _identifier(value: Any, name: str) -> str:
    text = _required_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{name} has invalid format")
    return text


def _link(value: Any) -> str:
    text = _required_text(value, "orderLinkId")
    if not _LINK_RE.fullmatch(text):
        raise ValueError("orderLinkId has invalid format")
    return text


def _symbol(value: Any) -> str:
    text = _required_text(value, "symbol").upper().replace("/", "").replace("-", "")
    if len(text) > 30 or not text.isalnum():
        raise ValueError("symbol has invalid format")
    return text


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise TypeError(f"{name} must be boolean")


def _position_idx(value: Any) -> int:
    parsed = _nonnegative_int(value, "position_idx")
    if parsed not in {0, 1, 2}:
        raise ValueError("position_idx must be 0, 1, or 2")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = _nonnegative_int(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative_int(value: Any, name: str) -> int:
    if value is None or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        parsed_decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if not parsed_decimal.is_finite() or parsed_decimal != parsed_decimal.to_integral_value():
        raise ValueError(f"{name} must be a whole integer")
    parsed = int(parsed_decimal)
    if parsed < 0:
        raise ValueError(f"{name} must not be negative")
    return parsed


def _decimal(value: Any, name: str, *, positive: bool = False) -> str:
    parsed = _decimal_value(value, name)
    if parsed < 0 or (positive and parsed <= 0):
        raise ValueError(f"{name} is outside the allowed range")
    return _canonical_decimal(parsed)


def _optional_decimal(value: Any, name: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    return _decimal(value, name, positive=True)


def _decimal_value(value: Any, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text
