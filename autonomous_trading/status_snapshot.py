"""Non-blocking operator snapshot for the autonomous PAPER loop.

The trading worker intentionally owns its in-memory state lock across a full
canonical tick. Operator status reads must never wait for that execution lock;
when it is busy we serve the last committed ProjectDatabase state instead.
"""
from __future__ import annotations

import json
from typing import Any


def nonblocking_loop_snapshot(loop: Any) -> dict[str, Any]:
    """Return PAPER status without waiting for the worker's execution lock."""
    lock = loop._lock
    acquired = lock.acquire(blocking=False)
    if acquired:
        try:
            state = loop.snapshot()
            state["snapshot_state_source"] = "memory"
            return state
        finally:
            lock.release()

    market = loop.stream.snapshot()
    row = loop.database.get_json(loop.state_namespace, loop.scope)
    raw = row.get("value") if isinstance(row, dict) else None
    if not isinstance(raw, dict):
        state = {}
    else:
        state = json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))

    # The committed state is already canonical/normalized. Mark the copy using
    # current market data when possible, but never mutate or wait for the worker.
    try:
        loop._mark_state_to_market(state, market, update_timestamp=False)
    except Exception:
        pass

    state["market_stream"] = {
        key: market.get(key)
        for key in ("status", "connected", "verified", "age_seconds", "last_error")
    }
    state["real_execution_enabled"] = False
    state["database_backed"] = True
    state["database_scope"] = loop.scope
    state["backup_status"] = "error" if getattr(loop, "_last_backup_error", "") else "ok"
    state["backup_error"] = getattr(loop, "_last_backup_error", "")
    state["worker_running"] = bool(loop._thread and loop._thread.is_alive())
    state["source_of_truth"] = "autonomous_paper"
    state["legacy_virtual_account_deprecated"] = True
    state["mutation_on_read"] = False
    state["wait_event_min_interval_seconds"] = loop.wait_event_min_interval_seconds
    state["snapshot_state_source"] = "project_database_fallback"

    try:
        state["trade_history_count"] = len(loop.trade_history())
    except Exception:
        state["trade_history_count"] = len(state.get("trades", ())) if isinstance(state.get("trades"), list) else 0
    try:
        state["event_history_count"] = len(loop.event_history())
    except Exception:
        state["event_history_count"] = len(state.get("events", ())) if isinstance(state.get("events"), list) else 0
    return state


__all__ = ["nonblocking_loop_snapshot"]