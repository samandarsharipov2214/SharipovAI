"""Atomic persistent store for validated private Bybit order events."""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .bybit_order_state_types import (
    INSTANTANEOUS_CLOSED_STATUSES,
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    TOPICS,
    bind_aliases,
    environment as normalize_environment,
    finite_float,
    integer,
    merge_order_state,
    normalize_order_event,
    optional_identifier,
    positive_int,
    resolve_canonical,
    validate_document,
)


class BybitOrderStateStore:
    """Canonical, alias-aware state store for private order events."""

    def __init__(self, path: str | Path | None = None, *, environment: str | None = None) -> None:
        self.environment = normalize_environment(environment or os.getenv("EXCHANGE_MODE", "sandbox"))
        default_path = f"data/bybit_order_state_{self.environment}.json"
        self.path = Path(path or os.getenv("BYBIT_ORDER_STATE_FILE", default_path))
        configured_lag = finite_float(os.getenv("BYBIT_PRIVATE_EVENT_MAX_LAG_SECONDS", "30"), "max lag")
        self.max_message_lag_ms = int(min(max(configured_lag, 1.0), 300.0) * 1000)
        future_skew = integer(os.getenv("BYBIT_PRIVATE_EVENT_MAX_FUTURE_SKEW_MS", "1000"), "future skew")
        self.max_future_skew_ms = min(max(future_skew, 0), 5_000)
        self._lock = threading.RLock()

    def ingest_message(self, message: Mapping[str, Any], *, received_at_ms: int | None = None) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("message must be an object")
        topic = str(message.get("topic", "")).strip()
        if topic not in TOPICS:
            raise ValueError("unsupported private order topic")
        now_ms = positive_int(
            received_at_ms if received_at_ms is not None else int(time.time() * 1000),
            "received_at_ms",
        )
        creation_ms = positive_int(message.get("creationTime"), "creationTime")
        if creation_ms > now_ms + self.max_future_skew_ms:
            raise ValueError("message creationTime is in the future")
        if now_ms - creation_ms > self.max_message_lag_ms:
            raise ValueError("private order message is too old or replayed")
        rows = message.get("data")
        if not isinstance(rows, list) or not rows:
            raise ValueError("data must be a non-empty list")
        message_id = optional_identifier(message.get("id"), "message id")

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
                    state = normalize_order_event(
                        row,
                        topic=topic,
                        environment=self.environment,
                        message_id=message_id,
                        message_creation_ms=creation_ms,
                        received_at_ms=now_ms,
                        max_message_lag_ms=self.max_message_lag_ms,
                        future_skew_ms=self.max_future_skew_ms,
                    )
                    canonical = resolve_canonical(candidate_aliases, state.order_id, state.order_link_id)
                    existing_raw = candidate_orders.get(canonical) if canonical else None
                    if canonical is None:
                        canonical = f"order:{state.order_id}" if state.order_id else f"link:{state.order_link_id}"
                    outcome, merged = merge_order_state(existing_raw, state)
                    if outcome == "duplicate":
                        duplicates.append(canonical)
                    else:
                        candidate_orders[canonical] = merged.to_dict()
                        accepted.append(canonical)
                    bind_aliases(candidate_aliases, canonical, merged.order_id, merged.order_link_id)
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
            "open_orders": [value for value in values if value.get("status") in OPEN_STATUSES],
            "terminal_orders": [value for value in values if value.get("status") in TERMINAL_STATUSES],
            "instantaneous_closed_orders": [
                value for value in values if value.get("status") in INSTANTANEOUS_CLOSED_STATUSES
            ],
            "orders": values,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": {}, "aliases": {}, "updated_at_ms": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"order state file is unreadable: {type(exc).__name__}") from exc
        validate_document(data, environment=self.environment)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        validate_document(data, environment=self.environment)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
