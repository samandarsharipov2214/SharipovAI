"""Stable identities and namespaces for autonomous paper-trading records."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def scope_for_path(path: str | Path) -> str:
    return hashlib.sha256(str(Path(path).expanduser().resolve()).encode("utf-8")).hexdigest()[:20]


def new_trade_id() -> str:
    return f"paper_{uuid.uuid4().hex}"


def new_event_id() -> str:
    return f"paper_event_{uuid.uuid4().hex}"


def normalize_trade(raw: dict[str, Any], *, scope: str, index: int) -> dict[str, Any]:
    item = dict(raw)
    created_at_ms = _timestamp_ms(item.get("created_at_ms"), item.get("time"), fallback=index + 1)
    trade_id = str(item.get("trade_id") or "").strip()
    if not trade_id:
        trade_id = _legacy_id("paper_legacy", scope, index, item)
    _validate_id(trade_id, "trade_id")
    item["trade_id"] = trade_id
    item["created_at_ms"] = created_at_ms
    return item


def normalize_event(raw: dict[str, Any], *, scope: str, index: int) -> dict[str, Any]:
    item = dict(raw)
    created_at_ms = _timestamp_ms(item.get("created_at_ms"), item.get("time"), fallback=index + 1)
    event_id = str(item.get("event_id") or "").strip()
    if not event_id:
        event_id = _legacy_id("paper_event_legacy", scope, index, item)
    _validate_id(event_id, "event_id")
    item["event_id"] = event_id
    item["created_at_ms"] = created_at_ms
    return item


def _legacy_id(prefix: str, scope: str, index: int, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(f"{scope}:{index}:{canonical}".encode("utf-8")).hexdigest()[:40]
    return f"{prefix}_{digest}"


def _timestamp_ms(value: Any, iso_value: Any, *, fallback: int) -> int:
    if value not in (None, ""):
        parsed = int(value)
        if parsed > 0:
            return parsed
    try:
        parsed = int(datetime.fromisoformat(str(iso_value)).timestamp() * 1000)
        if parsed > 0:
            return parsed
    except Exception:
        pass
    return max(int(fallback), 1)


def _validate_id(value: str, name: str) -> None:
    if not value or len(value) > 128 or not all(char.isalnum() or char in "._:-" for char in value):
        raise ValueError(f"invalid {name}")


__all__ = [
    "new_event_id",
    "new_trade_id",
    "normalize_event",
    "normalize_trade",
    "scope_for_path",
]
