"""Paper-campaign cash book helpers.

The historical 10_000 USDT figure was a code default, not owner capital.
Canonical paper now starts at 100 USDT. Existing 10k churn ledgers are never
deleted automatically.

Operator env (all default off / empty):
- ``AUTONOMOUS_PAPER_INITIAL_CASH`` — starting cash for a new book (default 100).
- ``AUTONOMOUS_PAPER_CAMPAIGN_ID`` — optional namespace so a new campaign can
  start a fresh default state without wiping the previous book in the database.
- ``AUTONOMOUS_PAPER_REBASE_TO_INITIAL=1`` — fail-closed opt-in to reset the
  live cash/equity/peak book to ``initial_cash`` when positions are empty.
  Trades and events stay. Default off so tests and production cannot silently
  wipe a book. VPS rebase is a later deploy step.

``PAPER_FLAT_RECOVERY_POSITION_FACTOR`` — when the book is FLAT and equity is
below ``initial_cash``, a new BUY is sized at half of ``max_position_percent``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .trade_identity import scope_for_path

# Canonical paper starting cash. Not live capital.
DEFAULT_PAPER_INITIAL_CASH = 100.0

# When FLAT and equity < initial_cash, cap new entries to this fraction of
# max_position_percent (10% -> 5% -> 5 USDT on a 100 USDT book).
PAPER_FLAT_RECOVERY_POSITION_FACTOR = 0.5

_TRUE = {"1", "true", "yes", "on"}


def paper_campaign_id() -> str:
    """Return a sanitized campaign id, or empty when unset/invalid."""
    raw = str(os.getenv("AUTONOMOUS_PAPER_CAMPAIGN_ID", "") or "").strip()
    if not raw or len(raw) > 64:
        return ""
    if not all(char.isalnum() or char in "._:-" for char in raw):
        return ""
    return raw


def rebase_to_initial_enabled() -> bool:
    """Fail-closed: rebase only when the operator explicitly opts in."""
    return str(os.getenv("AUTONOMOUS_PAPER_REBASE_TO_INITIAL", "") or "").strip().lower() in _TRUE


def paper_state_scope(state_file: str | Path) -> str:
    """Database scope for the live paper book.

    A non-empty campaign id namespaces the key so the previous campaign ledger
    remains stored under the old scope.
    """
    base = scope_for_path(state_file)
    campaign = paper_campaign_id()
    return f"{base}:{campaign}" if campaign else base


def maybe_rebase_paper_book(
    state: dict[str, Any],
    *,
    initial_cash: float,
) -> tuple[dict[str, Any], str]:
    """Reset the live cash book to ``initial_cash`` when explicitly requested.

    No-op unless all of:
    - ``AUTONOMOUS_PAPER_REBASE_TO_INITIAL=1``
    - ``positions`` is an empty object (FLAT)
    Immutable trades/events/last-close evidence are kept.
    """
    if not rebase_to_initial_enabled():
        return state, ""
    positions = state.get("positions")
    if not isinstance(positions, dict) or positions:
        return state, ""
    cash = _finite_or(state.get("cash"), 0.0) or 0.0
    equity = _finite_or(state.get("equity"), cash) or cash
    peak = _finite_or(state.get("peak_equity"), equity) or equity
    recorded = state.get("configured_initial_cash")
    recorded_cash = None if recorded in (None, "") else _finite_or(recorded, None)
    already_aligned = (
        abs(cash - initial_cash) <= 1e-12
        and abs(equity - initial_cash) <= 1e-12
        and abs(peak - initial_cash) <= 1e-12
        and recorded_cash is not None
        and abs(recorded_cash - initial_cash) <= 1e-12
    )
    if already_aligned:
        return state, ""
    next_state = dict(state)
    next_state["cash"] = float(initial_cash)
    next_state["equity"] = float(initial_cash)
    next_state["peak_equity"] = float(initial_cash)
    next_state["unrealized_pnl"] = 0.0
    next_state["configured_initial_cash"] = float(initial_cash)
    campaign = paper_campaign_id()
    if campaign:
        next_state["campaign_id"] = campaign
    next_state["paper_rebased_to_initial"] = True
    reason = (
        "paper_campaign_rebase_to_initial: FLAT book cash/equity/peak reset to "
        f"{initial_cash}; immutable trades/events were not deleted"
    )
    next_state["last_action"] = "WAIT"
    next_state["last_reason"] = reason
    return next_state, reason


def _finite_or(value: Any, default: float | None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default
    return parsed


__all__ = [
    "DEFAULT_PAPER_INITIAL_CASH",
    "PAPER_FLAT_RECOVERY_POSITION_FACTOR",
    "maybe_rebase_paper_book",
    "paper_campaign_id",
    "paper_state_scope",
    "rebase_to_initial_enabled",
]
