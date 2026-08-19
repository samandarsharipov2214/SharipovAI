"""Bounded, fail-closed Bybit order-book evidence for Market Intelligence.

The module deliberately stores only a compact top-of-book/depth summary.  It does
not retain raw websocket payloads or a full historical order book.

Bybit V5 order-book semantics used here:
- a fresh subscription starts with a ``snapshot``;
- a later ``snapshot`` replaces local state;
- ``u == 1`` indicates a service-restart snapshot/reset;
- ``u`` is the update identifier and is sequential for the order-book stream.

Callers remain responsible for reconstructing delta updates into a current local
book.  This module validates the update sequence and turns the reconstructed top
levels into bounded decision evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
import math
from typing import Iterable, Sequence


class BookEvidenceQuality(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    INVALID = "invalid"
    SEQUENCE_GAP = "sequence_gap"


@dataclass(frozen=True, slots=True)
class BybitSequenceState:
    """Minimal update-id state; it never stores order-book levels."""

    update_id: int | None = None
    has_snapshot: bool = False


@dataclass(frozen=True, slots=True)
class BybitSequenceCheck:
    state: BybitSequenceState
    usable: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OrderBookEvidence:
    symbol: str
    source: str
    observed_at_ms: int
    received_at_ms: int
    update_id: int
    cross_sequence: int | None
    best_bid: float | None
    best_ask: float | None
    spread_bps: float | None
    bid_depth_quote: float
    ask_depth_quote: float
    depth_imbalance: float
    levels_per_side: int
    age_ms: int
    quality: BookEvidenceQuality
    usable_for_decision: bool
    quality_reasons: tuple[str, ...]


def check_bybit_sequence(
    state: BybitSequenceState,
    *,
    message_type: str,
    update_id: int,
) -> BybitSequenceCheck:
    """Validate snapshot/delta ordering without retaining any book data.

    A snapshot (including restart ``u == 1``) establishes a new baseline.  A
    delta before any snapshot fails closed.  Once a baseline exists, duplicate,
    regressing, or skipped update ids fail closed and require a fresh snapshot.
    """

    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id <= 0:
        return BybitSequenceCheck(
            state=BybitSequenceState(), usable=False, reason="invalid_update_id"
        )

    normalized_type = message_type.strip().lower()
    if normalized_type not in {"snapshot", "delta"}:
        return BybitSequenceCheck(state=state, usable=False, reason="invalid_message_type")

    if normalized_type == "snapshot" or update_id == 1:
        return BybitSequenceCheck(
            state=BybitSequenceState(update_id=update_id, has_snapshot=True),
            usable=True,
        )

    if not state.has_snapshot or state.update_id is None:
        return BybitSequenceCheck(
            state=BybitSequenceState(), usable=False, reason="missing_snapshot"
        )

    if update_id <= state.update_id:
        return BybitSequenceCheck(
            state=BybitSequenceState(), usable=False, reason="non_monotonic_update"
        )

    if update_id != state.update_id + 1:
        return BybitSequenceCheck(
            state=BybitSequenceState(), usable=False, reason="update_id_gap"
        )

    return BybitSequenceCheck(
        state=BybitSequenceState(update_id=update_id, has_snapshot=True), usable=True
    )


def build_order_book_evidence(
    *,
    symbol: str,
    bids: Sequence[Sequence[object]] | Iterable[Sequence[object]],
    asks: Sequence[Sequence[object]] | Iterable[Sequence[object]],
    observed_at_ms: int,
    received_at_ms: int,
    update_id: int,
    cross_sequence: int | None = None,
    max_age_ms: int = 2_000,
    max_levels: int = 10,
    sequence_usable: bool = True,
    sequence_reason: str | None = None,
) -> OrderBookEvidence:
    """Create bounded market evidence from an already reconstructed book.

    At most ``max_levels`` levels from each side are consumed.  Invalid, stale,
    crossed, empty, or sequence-broken evidence is retained for diagnostics but
    is never marked usable for a trading decision.
    """

    if isinstance(max_age_ms, bool) or not isinstance(max_age_ms, int) or max_age_ms < 0:
        raise ValueError("max_age_ms must be a non-negative integer")
    if isinstance(max_levels, bool) or not isinstance(max_levels, int) or not 1 <= max_levels <= 50:
        raise ValueError("max_levels must be an integer between 1 and 50")
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (observed_at_ms, received_at_ms)
    ):
        raise ValueError("timestamps must be non-negative integer milliseconds")
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id <= 0:
        raise ValueError("update_id must be a positive integer")
    if cross_sequence is not None and (
        isinstance(cross_sequence, bool)
        or not isinstance(cross_sequence, int)
        or cross_sequence <= 0
    ):
        raise ValueError("cross_sequence must be a positive integer when present")

    reasons: list[str] = []
    parsed_bids = _bounded_levels(bids, max_levels=max_levels, side="bid", reasons=reasons)
    parsed_asks = _bounded_levels(asks, max_levels=max_levels, side="ask", reasons=reasons)

    age_ms = max(0, received_at_ms - observed_at_ms)
    if observed_at_ms > received_at_ms:
        reasons.append("future_exchange_timestamp")
    elif age_ms > max_age_ms:
        reasons.append("stale_book")

    if not sequence_usable:
        reasons.append(sequence_reason or "sequence_unusable")

    best_bid = max((price for price, _ in parsed_bids), default=None)
    best_ask = min((price for price, _ in parsed_asks), default=None)
    if best_bid is None:
        reasons.append("missing_bid")
    if best_ask is None:
        reasons.append("missing_ask")
    if best_bid is not None and best_ask is not None and best_bid >= best_ask:
        reasons.append("crossed_or_locked_book")

    spread_bps: float | None = None
    if best_bid is not None and best_ask is not None and best_bid < best_ask:
        midpoint = (best_bid + best_ask) / 2.0
        spread_bps = round((best_ask - best_bid) / midpoint * 10_000.0, 8)

    bid_depth_quote = sum(price * size for price, size in parsed_bids)
    ask_depth_quote = sum(price * size for price, size in parsed_asks)
    total_depth = bid_depth_quote + ask_depth_quote
    imbalance = (
        (bid_depth_quote - ask_depth_quote) / total_depth if total_depth > 0 else 0.0
    )

    if any(reason in reasons for reason in ("stale_book",)):
        quality = BookEvidenceQuality.STALE
    elif not sequence_usable:
        quality = BookEvidenceQuality.SEQUENCE_GAP
    elif reasons:
        quality = BookEvidenceQuality.INVALID
    else:
        quality = BookEvidenceQuality.FRESH

    return OrderBookEvidence(
        symbol=symbol.strip().upper(),
        source="bybit",
        observed_at_ms=observed_at_ms,
        received_at_ms=received_at_ms,
        update_id=update_id,
        cross_sequence=cross_sequence,
        best_bid=best_bid,
        best_ask=best_ask,
        spread_bps=spread_bps,
        bid_depth_quote=round(bid_depth_quote, 8),
        ask_depth_quote=round(ask_depth_quote, 8),
        depth_imbalance=round(imbalance, 8),
        levels_per_side=max_levels,
        age_ms=age_ms,
        quality=quality,
        usable_for_decision=quality is BookEvidenceQuality.FRESH,
        quality_reasons=tuple(dict.fromkeys(reasons)),
    )


def _bounded_levels(
    levels: Sequence[Sequence[object]] | Iterable[Sequence[object]],
    *,
    max_levels: int,
    side: str,
    reasons: list[str],
) -> tuple[tuple[float, float], ...]:
    parsed: list[tuple[float, float]] = []
    for raw_level in islice(iter(levels), max_levels):
        try:
            if len(raw_level) < 2:  # type: ignore[arg-type]
                raise ValueError
            price = float(raw_level[0])
            size = float(raw_level[1])
        except (TypeError, ValueError, IndexError):
            reasons.append(f"invalid_{side}_level")
            continue
        if not all(math.isfinite(value) and value > 0 for value in (price, size)):
            reasons.append(f"invalid_{side}_level")
            continue
        parsed.append((price, size))
    return tuple(parsed)


__all__ = [
    "BookEvidenceQuality",
    "BybitSequenceCheck",
    "BybitSequenceState",
    "OrderBookEvidence",
    "build_order_book_evidence",
    "check_bybit_sequence",
]
