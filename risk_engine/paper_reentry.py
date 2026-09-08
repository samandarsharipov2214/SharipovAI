"""PAPER-only failed-thesis quarantine. This module grants no execution authority."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

# The active Council signal measures rolling 24-hour change. Replacing a quote
# timestamp does not invalidate the memory of a stopped thesis on that horizon.
# Fixed risk-containment policy, not a fitted estimate of profitable waiting time.
PAPER_POST_STOP_COOLDOWN_MS = 24 * 60 * 60 * 1000
PAPER_REENTRY_POLICY_VERSION = "paper-post-stop-v1"
POST_STOP_BLOCK = "paper_post_stop_cooldown"
POST_STOP_EVIDENCE_BLOCK = "paper_post_stop_evidence_unavailable"


def post_stop_reentry_block(
    last_close: Mapping[str, Any] | None, *, symbol: str, now_ms: int
) -> str | None:
    """Veto a new BUY using only previously observed, same-symbol close facts.

    Passing this gate is not a BUY recommendation. Existing Council, Risk,
    Security, transaction-cost and instrument checks still have to pass.
    Callers must never apply this entry gate to a position-reducing SELL.
    """
    if last_close is None:
        return None
    invalid = f"{POST_STOP_EVIDENCE_BLOCK}: verified same-symbol close facts required"
    if not isinstance(last_close, Mapping):
        return invalid
    if (
        last_close.get("symbol") != str(symbol).upper()
        or last_close.get("side") != "SELL"
        or not str(last_close.get("trade_id") or "").strip()
        or last_close.get("verified_market_data") is not True
    ):
        return invalid
    closed = last_close.get("closed_at_ms")
    pnl = last_close.get("net_pnl")
    if (
        isinstance(now_ms, bool)
        or not isinstance(now_ms, int)
        or isinstance(closed, bool)
        or not isinstance(closed, int)
        or closed <= 0
        or now_ms < closed
        or isinstance(pnl, bool)
        or not isinstance(pnl, (int, float))
        or not math.isfinite(pnl)
    ):
        return invalid
    reason = str(last_close.get("reason") or "")
    stopped = reason in {"protective_stop_loss", "stop_loss"}
    if not stopped and not (
        reason in {"protective_take_profit", "take_profit", "protective_momentum_exit"}
        or reason.startswith("canonical_council_sell:")
    ):
        return invalid
    eligible_at = closed + PAPER_POST_STOP_COOLDOWN_MS
    if stopped and now_ms < eligible_at:
        return (
            f"{POST_STOP_BLOCK}: {symbol} stopped trade {last_close['trade_id']}; "
            f"net_pnl={pnl:.12g}; eligible_at_ms={eligible_at}; "
            f"policy={PAPER_REENTRY_POLICY_VERSION}"
        )
    return None
