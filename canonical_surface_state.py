"""Read-only canonical state projection for Telegram and other presentation surfaces.

This module intentionally has no FastAPI dependency and never starts workers or
mutates paper state. Website/Telegram/mobile adapters can therefore read the
same ProjectDatabase-backed account history without importing the deprecated
demo sandbox.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from storage import ProjectDatabase, list_json_items

_STATE_NAMESPACE = "autonomous_paper_state"


def load_canonical_paper_state(database: ProjectDatabase | None = None) -> dict[str, Any]:
    """Return one fail-closed projection of canonical autonomous PAPER state."""

    db = database or ProjectDatabase()
    db.initialize()
    state_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
    scope = _scope_for_path(state_file)
    current = db.get_json(_STATE_NAMESPACE, scope)
    if current is None or not isinstance(current.get("value"), dict):
        return {
            "status": "unavailable",
            "mode": "PAPER",
            "source_of_truth": "ProjectDatabase/CouncilAuthorizedPaperLoop",
            "database_backed": True,
            "equity": 0.0,
            "cash": 0.0,
            "net_pnl": 0.0,
            "total_fees": 0.0,
            "open_positions": 0,
            "positions": [],
            "trades": [],
            "exchange_status": {"mode": os.getenv("EXCHANGE_MODE", "sandbox"), "connected": False},
            "real_orders_blocked": True,
        }

    state = dict(current["value"])
    raw_positions = state.get("positions", {})
    if isinstance(raw_positions, dict):
        positions = [
            {"symbol": str(symbol), **dict(value)}
            for symbol, value in raw_positions.items()
            if isinstance(value, dict)
        ]
    elif isinstance(raw_positions, list):
        positions = [dict(value) for value in raw_positions if isinstance(value, dict)]
    else:
        positions = []

    trade_namespace = f"paper_trades:{scope}"
    trades = [
        dict(item["value"])
        for item in list_json_items(db, trade_namespace, limit=5_000)
        if isinstance(item.get("value"), dict)
    ]
    realized = _number(state.get("realized_pnl"))
    unrealized = _number(state.get("unrealized_pnl"))
    return {
        **state,
        "status": "ok",
        "mode": "PAPER",
        "source_of_truth": "ProjectDatabase/CouncilAuthorizedPaperLoop",
        "database_backed": True,
        "equity": _number(state.get("equity")),
        "cash": _number(state.get("cash")),
        "net_pnl": realized + unrealized,
        "total_fees": _number(state.get("total_fees")),
        "open_positions": len(positions),
        "positions": positions,
        "trades": trades,
        "trade_history_count": len(trades),
        "exchange_status": {
            "mode": os.getenv("EXCHANGE_MODE", "sandbox"),
            "connected": None,
        },
        "real_orders_blocked": True,
    }


def _scope_for_path(path: Path) -> str:
    canonical = str(path.expanduser().resolve()).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:20]


def _number(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed


__all__ = ["load_canonical_paper_state"]
