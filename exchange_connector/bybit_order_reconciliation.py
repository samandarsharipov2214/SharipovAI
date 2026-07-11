"""Fail-closed restart reconciliation for execution journals and private orders."""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from .bybit_order_state_types import (
    INSTANTANEOUS_CLOSED_STATUSES,
    MANAGED_ORDER_LINK_PREFIX,
    TERMINAL_STATUSES,
    TOLERANCE,
)


def reconcile_execution_journal(journal: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    journal_rows = journal.get("orders", []) if isinstance(journal, Mapping) else []
    tracked_rows = snapshot.get("orders", []) if isinstance(snapshot, Mapping) else []
    if not isinstance(journal_rows, list) or not isinstance(tracked_rows, list):
        raise TypeError("journal and snapshot must contain order lists")
    if any(not isinstance(row, Mapping) for row in journal_rows):
        raise RuntimeError("execution journal contains an invalid row")

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
    matched_closed: list[str] = []
    matched_indices: set[int] = set()
    accepted = [row for row in journal_rows if row.get("status") == "accepted"]

    for index, row in enumerate(accepted):
        order_id = str(row.get("order_id", "")).strip()
        link_id = str(row.get("order_link_id", "")).strip()
        identity = order_id or link_id or f"journal-index:{index}"
        order_index = by_order.get(order_id) if order_id else None
        link_index = by_link.get(link_id) if link_id else None
        candidate_indices = {value for value in (order_index, link_index) if value is not None}
        tracked_index = next(iter(candidate_indices)) if len(candidate_indices) == 1 else None

        if len(candidate_indices) > 1:
            unresolved.append({"identity": identity, "reason": "journal identifiers resolve to different private orders"})
            continue
        if tracked_index is not None:
            mismatches = _reconciliation_mismatches(row, normalized_tracked[tracked_index])
            if mismatches:
                unresolved.append({"identity": identity, "reason": "field mismatch", "fields": mismatches})
                continue
        if not order_id:
            unresolved.append({"identity": identity, "reason": "execution journal order_id is required"})
            continue
        if not link_id or not link_id.startswith(MANAGED_ORDER_LINK_PREFIX):
            unresolved.append({"identity": identity, "reason": "managed execution journal order_link_id is required"})
            continue
        if order_index is None:
            unresolved.append({"identity": identity, "reason": "journal order_id is absent from private state"})
            continue
        if link_index is None:
            unresolved.append({"identity": identity, "reason": "journal order_link_id is absent from private state"})
            continue
        if order_index != link_index:
            unresolved.append({"identity": identity, "reason": "journal identifiers resolve to different private orders"})
            continue
        tracked_index = order_index
        tracked = normalized_tracked[tracked_index]
        identity_fields = []
        if str(tracked.get("order_id", "")).strip() != order_id:
            identity_fields.append("order_id")
        if str(tracked.get("order_link_id", "")).strip() != link_id:
            identity_fields.append("order_link_id")
        if identity_fields:
            unresolved.append({"identity": identity, "reason": "identifier mismatch", "fields": identity_fields})
            continue
        if tracked_index in matched_indices:
            unresolved.append({"identity": identity, "reason": "multiple journal rows resolve to one private order"})
            continue
        matched_indices.add(tracked_index)
        status = str(tracked.get("status", ""))
        if status in TERMINAL_STATUSES:
            matched_terminal.append(identity)
        elif status in INSTANTANEOUS_CLOSED_STATUSES:
            matched_closed.append(identity)
        else:
            matched_open.append(identity)

    for index, tracked in enumerate(normalized_tracked):
        if index in matched_indices or str(tracked.get("status")) in INSTANTANEOUS_CLOSED_STATUSES:
            continue
        identity = str(tracked.get("order_id") or tracked.get("order_link_id") or f"private-index:{index}")
        status = str(tracked.get("status", ""))
        unresolved.append({
            "identity": identity,
            "reason": f"private {status or 'unknown'} order missing from execution journal",
        })

    return {
        "status": "ok" if not unresolved else "blocked",
        "accepted_journal_orders": len(accepted),
        "matched_open": matched_open,
        "matched_terminal": matched_terminal,
        "matched_closed": matched_closed,
        "unresolved": unresolved,
        "restart_safe": not unresolved,
    }


def _reconciliation_mismatches(journal: Mapping[str, Any], tracked: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    environment = str(journal.get("environment") or journal.get("mode") or "").strip().lower()
    if environment in {"sandbox", "testnet"}:
        environment = "testnet"
    elif environment in {"live", "mainnet"}:
        environment = "mainnet"
    checks = {
        "environment": environment,
        "category": str(journal.get("category", "")).strip().lower(),
        "symbol": str(journal.get("symbol", "")).strip().upper(),
        "side": str(journal.get("side", "")).strip().title(),
    }
    for field, expected in checks.items():
        if not expected or str(tracked.get(field, "")) != expected:
            mismatches.append(field)
    try:
        journal_qty = float(journal.get("quantity", journal.get("qty")))
        if not isfinite(journal_qty) or abs(journal_qty - float(tracked.get("qty", -1))) > TOLERANCE:
            mismatches.append("qty")
    except (TypeError, ValueError):
        mismatches.append("qty")
    return mismatches
