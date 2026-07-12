"""Evidence-integrity rules for staged trading promotion.

Only trades backed by verified market data may influence paper-performance metrics
or unlock a higher execution stage. Synthetic, demo, fixture, timer-derived and
manually fabricated activity remains visible for diagnostics but is never accepted
as promotion evidence.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

_SYNTHETIC_SOURCES = {
    "demo",
    "fixture",
    "mock",
    "paper_activity_engine",
    "synthetic",
    "virtual_account_execution_engine",
}
_VERIFIED_MARKET_SOURCES = {
    "bybit_public_websocket",
    "bybit_websocket",
    "bybit_websocket_v5",
}


@dataclass(frozen=True, slots=True)
class EvidenceEligibility:
    eligible: bool
    source: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_trade_evidence(trade: Mapping[str, Any]) -> EvidenceEligibility:
    """Classify a closed paper trade without guessing missing evidence."""

    if not isinstance(trade, Mapping):
        return EvidenceEligibility(False, "", ("trade is not an object",))

    source = str(trade.get("source") or "").strip().lower()
    reasons: list[str] = []

    if not source:
        reasons.append("source is missing")
    elif source in _SYNTHETIC_SOURCES:
        reasons.append(f"synthetic source is not eligible: {source}")
    elif source not in _VERIFIED_MARKET_SOURCES:
        reasons.append(f"market source is not approved: {source}")

    if trade.get("verified_market_data") is not True:
        reasons.append("verified_market_data must be true")

    trade_id = str(trade.get("trade_id") or trade.get("id") or "").strip()
    if not trade_id:
        reasons.append("stable trade id is missing")

    created_at_ms = trade.get("created_at_ms")
    if isinstance(created_at_ms, bool) or not isinstance(created_at_ms, int) or created_at_ms <= 0:
        reasons.append("created_at_ms must be a positive integer")

    _require_positive_finite(trade.get("price"), "price", reasons)
    _require_positive_finite(trade.get("quantity"), "quantity", reasons)
    _require_finite(trade.get("net_pnl"), "net_pnl", reasons)

    side = str(trade.get("side") or "").strip().upper()
    if side != "SELL":
        reasons.append("only closed SELL records are performance evidence")

    return EvidenceEligibility(not reasons, source, tuple(reasons))


def eligible_closed_trades(trades: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split closed trades into eligible and rejected evidence records."""

    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in trades:
        if not isinstance(raw, dict):
            rejected.append({"trade": raw, "eligibility": assess_trade_evidence({}).to_dict()})
            continue
        result = assess_trade_evidence(raw)
        if result.eligible:
            eligible.append(raw)
        else:
            rejected.append({"trade": raw, "eligibility": result.to_dict()})
    return eligible, rejected


def _require_finite(value: Any, name: str, reasons: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        reasons.append(f"{name} must be finite")


def _require_positive_finite(value: Any, name: str, reasons: list[str]) -> None:
    before = len(reasons)
    _require_finite(value, name, reasons)
    if len(reasons) == before and float(value) <= 0:
        reasons.append(f"{name} must be positive")


__all__ = ["EvidenceEligibility", "assess_trade_evidence", "eligible_closed_trades"]
