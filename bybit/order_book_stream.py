"""Bounded Bybit V5 snapshot/delta reconstruction for Market Intelligence.

This module accepts already-decoded public order-book websocket messages. It keeps
only a bounded current book in memory and emits compact ``OrderBookEvidence``;
it never persists raw websocket payloads or historical books.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping, Sequence

from .order_book_evidence import (
    BybitSequenceState,
    OrderBookEvidence,
    build_order_book_evidence,
    check_bybit_sequence,
)


@dataclass(slots=True)
class BoundedBybitOrderBook:
    """Reconstruct one Bybit order-book topic with bounded in-memory state."""

    symbol: str
    max_levels: int = 50
    max_age_ms: int = 2_000
    _bids: dict[float, float] = field(default_factory=dict, init=False, repr=False)
    _asks: dict[float, float] = field(default_factory=dict, init=False, repr=False)
    _sequence: BybitSequenceState = field(default_factory=BybitSequenceState, init=False, repr=False)

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        if isinstance(self.max_levels, bool) or not isinstance(self.max_levels, int) or not 1 <= self.max_levels <= 50:
            raise ValueError("max_levels must be an integer between 1 and 50")
        if isinstance(self.max_age_ms, bool) or not isinstance(self.max_age_ms, int) or self.max_age_ms < 0:
            raise ValueError("max_age_ms must be a non-negative integer")

    @property
    def level_counts(self) -> tuple[int, int]:
        """Return bounded bid/ask counts without exposing mutable book state."""
        return len(self._bids), len(self._asks)

    def reset(self) -> None:
        """Discard local state so a fresh snapshot is required."""
        self._bids.clear()
        self._asks.clear()
        self._sequence = BybitSequenceState()

    def apply_message(self, message: Mapping[str, object], *, received_at_ms: int) -> OrderBookEvidence:
        """Apply one decoded Bybit snapshot/delta and return compact evidence.

        Bybit documents snapshot replacement semantics and delta actions as:
        size=0 deletes, a missing price inserts, and an existing price updates.
        Any malformed message or unusable update sequence fails closed by raising
        ``ValueError`` after resetting local state where reconstruction is unsafe.
        """
        if isinstance(received_at_ms, bool) or not isinstance(received_at_ms, int) or received_at_ms < 0:
            raise ValueError("received_at_ms must be a non-negative integer")

        message_type = str(message.get("type", "")).strip().lower()
        if message_type not in {"snapshot", "delta"}:
            raise ValueError("order-book message type must be snapshot or delta")

        data = message.get("data")
        if not isinstance(data, Mapping):
            raise ValueError("order-book message data must be a mapping")

        symbol = str(data.get("s", "")).strip().upper()
        if symbol != self.symbol:
            raise ValueError("order-book symbol does not match reconstructor symbol")

        observed_at_ms = _positive_int(message.get("ts"), name="ts", allow_zero=True)
        update_id = _positive_int(data.get("u"), name="u")
        cross_sequence = _positive_int(data.get("seq"), name="seq")

        sequence = check_bybit_sequence(
            self._sequence,
            message_type=message_type,
            update_id=update_id,
        )
        if not sequence.usable:
            self.reset()
            raise ValueError(f"unusable order-book sequence: {sequence.reason}")

        bids = _parse_updates(data.get("b"), side="bid")
        asks = _parse_updates(data.get("a"), side="ask")

        # Bybit uses ``u == 1`` to signal a service-restart snapshot.  Although
        # a normal snapshot has ``type == snapshot``, treating the restart
        # marker as a delta would merge a new server book with stale levels from
        # the pre-restart connection.  Sequence validation already establishes
        # a new baseline for this marker; reconstruction must do the same.
        if message_type == "snapshot" or update_id == 1:
            self._bids = {price: size for price, size in bids if size > 0}
            self._asks = {price: size for price, size in asks if size > 0}
        else:
            _apply_delta(self._bids, bids)
            _apply_delta(self._asks, asks)

        self._trim()
        self._sequence = sequence.state

        evidence = build_order_book_evidence(
            symbol=self.symbol,
            bids=self._sorted_bids(),
            asks=self._sorted_asks(),
            observed_at_ms=observed_at_ms,
            received_at_ms=received_at_ms,
            update_id=update_id,
            cross_sequence=cross_sequence,
            max_age_ms=self.max_age_ms,
            max_levels=self.max_levels,
            sequence_usable=True,
        )
        if not evidence.usable_for_decision:
            # Keep a valid reconstructed book for diagnostics/future updates, but
            # the emitted evidence itself remains fail-closed for this decision.
            return evidence
        return evidence

    def _trim(self) -> None:
        if len(self._bids) > self.max_levels:
            keep = sorted(self._bids, reverse=True)[: self.max_levels]
            self._bids = {price: self._bids[price] for price in keep}
        if len(self._asks) > self.max_levels:
            keep = sorted(self._asks)[: self.max_levels]
            self._asks = {price: self._asks[price] for price in keep}

    def _sorted_bids(self) -> tuple[tuple[float, float], ...]:
        return tuple((price, self._bids[price]) for price in sorted(self._bids, reverse=True))

    def _sorted_asks(self) -> tuple[tuple[float, float], ...]:
        return tuple((price, self._asks[price]) for price in sorted(self._asks))


def _positive_int(value: object, *, name: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def _parse_updates(value: object, *, side: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{side} updates must be a sequence")
    parsed: list[tuple[float, float]] = []
    for raw in value:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or len(raw) < 2:
            raise ValueError(f"invalid {side} level")
        try:
            price = float(raw[0])
            size = float(raw[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(f"invalid {side} level") from exc
        if not math.isfinite(price) or price <= 0 or not math.isfinite(size) or size < 0:
            raise ValueError(f"invalid {side} level")
        parsed.append((price, size))
    return tuple(parsed)


def _apply_delta(book: dict[float, float], updates: tuple[tuple[float, float], ...]) -> None:
    for price, size in updates:
        if size == 0:
            book.pop(price, None)
        else:
            book[price] = size


__all__ = ["BoundedBybitOrderBook"]
