"""Bounded, read-only operator trace for canonical paper decisions."""
from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Any

from storage import ProjectDatabase

TRACE_NAMESPACE = "council_decision_trace"
_MAX_REASON = 800
_MAX_LIST = 32


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("invalid symbol")
    return clean


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_MAX_REASON]
    if isinstance(value, Mapping):
        return {str(key)[:80]: _safe_value(item) for key, item in list(value.items())[:_MAX_LIST]}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in list(value)[:_MAX_LIST]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:_MAX_REASON]


def persist_decision_trace(
    database: ProjectDatabase,
    symbol: str,
    updates: Mapping[str, Any],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Persist exactly one latest trace per symbol; history remains in canonical events/trades."""
    clean_symbol = _symbol(symbol)
    existing = database.get_json(TRACE_NAMESPACE, clean_symbol)
    payload = dict(existing.get("value") or {}) if isinstance(existing, dict) else {}
    payload.update({str(key): _safe_value(value) for key, value in updates.items()})
    payload["symbol"] = clean_symbol
    payload["updated_at_ms"] = int(now_ms or time.time() * 1000)
    payload["trace_contract"] = "canonical_decision_trace_v1"
    database.put_json(TRACE_NAMESPACE, clean_symbol, payload)
    return payload


def read_decision_trace(database: ProjectDatabase, symbol: str) -> dict[str, Any] | None:
    row = database.get_json(TRACE_NAMESPACE, _symbol(symbol))
    if not isinstance(row, dict) or not isinstance(row.get("value"), dict):
        return None
    return dict(row["value"])


def read_decision_traces(database: ProjectDatabase, symbols: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for symbol in symbols:
        clean = _symbol(symbol)
        if clean in seen:
            continue
        seen.add(clean)
        trace = read_decision_trace(database, clean)
        if trace is not None:
            rows.append(trace)
    rows.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
    return rows


__all__ = [
    "TRACE_NAMESPACE",
    "persist_decision_trace",
    "read_decision_trace",
    "read_decision_traces",
]
