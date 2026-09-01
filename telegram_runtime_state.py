"""Canonical read-only state projection for Telegram surfaces.

Telegram must never fall back to the deprecated demo account.  This module is
intentionally independent from the ``dashboard`` package so it can be imported
without creating the historical dashboard <-> Telegram circular import.
"""
from __future__ import annotations

import math
from typing import Any


def unavailable_state(reason: str) -> dict[str, Any]:
    """Return an explicit fail-closed state without fabricated financial data."""

    return {
        "status": "unavailable",
        "data_available": False,
        "source_of_truth": "autonomous_paper",
        "mode": "UNAVAILABLE",
        "equity": None,
        "cash": None,
        "pnl": None,
        "net_pnl": None,
        "realized_pnl": None,
        "unrealized_pnl": None,
        "total_fees": None,
        "deployed_notional": None,
        "reserve_amount": None,
        "open_positions": None,
        "positions": {},
        "trades": [],
        "trade_count": None,
        "last_action": None,
        "last_reason": None,
        "worker_running": False,
        "database_backed": False,
        "market_verified": False,
        "error": str(reason),
        "exchange_status": {
            "mode": "virtual_execution_only",
            "connected": False,
        },
        "integration": {
            "website": True,
            "mini_app": True,
            "telegram": True,
            "source": "autonomous_paper",
        },
    }


def canonical_state_from_app(app: Any) -> dict[str, Any]:
    """Project the canonical autonomous-paper runtime into Telegram's contract."""

    state = getattr(app, "state", None)
    loop = getattr(state, "autonomous_paper_loop", None)
    if loop is None:
        return unavailable_state("autonomous_paper_loop_missing")

    try:
        raw = _nonblocking_paper_snapshot(loop)
    except Exception as exc:  # pragma: no cover - exact runtime failures vary
        return unavailable_state(f"{type(exc).__name__}: {exc}")

    if not isinstance(raw, dict):
        return unavailable_state("autonomous_paper_snapshot_invalid")

    positions = raw.get("positions")
    if not isinstance(positions, dict):
        return unavailable_state("autonomous_paper_positions_invalid")

    trades = _canonical_trades(loop, raw)
    market = raw.get("market_stream") if isinstance(raw.get("market_stream"), dict) else {}

    realized = _finite(raw.get("realized_pnl"), 0.0)
    unrealized = _finite(raw.get("unrealized_pnl"), 0.0)
    trade_count = _integer(raw.get("trade_history_count"), len(trades))

    return {
        "status": "ok",
        "data_available": True,
        "source_of_truth": str(raw.get("source_of_truth") or "autonomous_paper"),
        "mode": str(raw.get("mode") or "autonomous_paper").upper(),
        "equity": _finite(raw.get("equity"), 0.0),
        "cash": _finite(raw.get("cash"), 0.0),
        "pnl": realized + unrealized,
        "net_pnl": realized + unrealized,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_fees": _finite(raw.get("total_fees"), 0.0),
        "deployed_notional": _finite(raw.get("deployed_notional"), 0.0),
        "reserve_amount": _finite(raw.get("reserve_amount"), 0.0),
        "open_positions": len(positions),
        "positions": positions,
        "trades": trades,
        "trade_count": trade_count,
        "last_action": raw.get("last_action"),
        "last_reason": raw.get("last_reason"),
        "worker_running": bool(raw.get("worker_running")),
        "database_backed": bool(raw.get("database_backed")),
        "database_scope": raw.get("database_scope"),
        "market_verified": bool(market.get("verified")),
        "market_age_seconds": market.get("age_seconds"),
        "mutation_on_read": bool(raw.get("mutation_on_read", False)),
        "exchange_status": {
            "mode": "virtual_execution_only",
            "connected": bool(market.get("verified")),
        },
        "integration": {
            "website": True,
            "mini_app": True,
            "telegram": True,
            "source": "autonomous_paper",
        },
    }



def _nonblocking_paper_snapshot(loop: Any) -> Any:
    """Read PAPER state without waiting on the worker execution lock."""

    lock = getattr(loop, "_lock", None)
    if lock is not None:
        from autonomous_trading.status_snapshot import nonblocking_loop_snapshot

        return nonblocking_loop_snapshot(loop)
    snapshot = getattr(loop, "snapshot", None)
    if not callable(snapshot):
        raise RuntimeError("autonomous_paper_snapshot_missing")
    return snapshot()


def _finite(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _integer(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(parsed, 0)


def _canonical_trades(loop: Any, raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer the loop's history reader over a bounded snapshot cache."""

    reader = getattr(loop, "trade_history", None)
    if callable(reader):
        try:
            rows = reader(limit=200)
        except Exception:
            rows = None
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return [item for item in (raw.get("trades") or []) if isinstance(item, dict)]


__all__ = ["canonical_state_from_app", "unavailable_state"]
