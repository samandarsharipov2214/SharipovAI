"""Fail-closed cross-source market-evidence quality for Market Intelligence.

This module compares an already bounded Bybit order-book evidence snapshot with a
bounded ticker quote. It performs no network I/O, stores no history, and has no
execution authority. Missing, stale, invalid, or materially conflicting inputs
remain diagnostic evidence but are not marked decision-usable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from .models import TickerInfo
from .order_book_evidence import OrderBookEvidence


class MarketEvidenceQuality(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    CONFLICTING = "conflicting"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CrossSourceMarketEvidence:
    symbol: str
    source_pair: tuple[str, str]
    ticker_received_at_ms: int
    evaluated_at_ms: int
    ticker_age_ms: int
    ticker_best_bid: float | None
    ticker_best_ask: float | None
    ticker_midpoint: float | None
    book_midpoint: float | None
    midpoint_divergence_bps: float | None
    quality: MarketEvidenceQuality
    usable_for_decision: bool
    quality_reasons: tuple[str, ...]
    execution_authority: bool = False


def evaluate_cross_source_market_evidence(
    *,
    ticker: TickerInfo,
    order_book: OrderBookEvidence,
    ticker_received_at_ms: int,
    evaluated_at_ms: int,
    max_ticker_age_ms: int = 2_000,
    max_midpoint_divergence_bps: float = 25.0,
) -> CrossSourceMarketEvidence:
    """Compare ticker BBO with bounded order-book evidence conservatively.

    The ticker has no intrinsic exchange timestamp in the current model, so its
    freshness is measured from the explicit caller-supplied receipt time. The
    order-book primitive retains its own exchange/receipt freshness checks.
    """

    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (ticker_received_at_ms, evaluated_at_ms, max_ticker_age_ms)
    ):
        raise ValueError("timestamps and max_ticker_age_ms must be non-negative integers")
    if isinstance(max_midpoint_divergence_bps, bool):
        raise ValueError("max_midpoint_divergence_bps must be a finite non-negative number")
    try:
        divergence_limit = float(max_midpoint_divergence_bps)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_midpoint_divergence_bps must be a finite non-negative number") from exc
    if not math.isfinite(divergence_limit) or divergence_limit < 0:
        raise ValueError("max_midpoint_divergence_bps must be a finite non-negative number")

    ticker_symbol = str(ticker.symbol or "").strip().upper()
    book_symbol = str(order_book.symbol or "").strip().upper()
    symbol = ticker_symbol or book_symbol
    reasons: list[str] = []

    if not ticker_symbol or not book_symbol or ticker_symbol != book_symbol:
        reasons.append("symbol_mismatch")

    ticker_age_ms = max(0, evaluated_at_ms - ticker_received_at_ms)
    if ticker_received_at_ms > evaluated_at_ms:
        reasons.append("future_ticker_receipt")
    elif ticker_age_ms > max_ticker_age_ms:
        reasons.append("stale_ticker")

    if not order_book.usable_for_decision:
        reasons.append("order_book_unusable")
        reasons.extend(f"order_book:{reason}" for reason in order_book.quality_reasons)

    ticker_bid = _positive_float(ticker.bid_price)
    ticker_ask = _positive_float(ticker.ask_price)
    if ticker_bid is None:
        reasons.append("invalid_ticker_bid")
    if ticker_ask is None:
        reasons.append("invalid_ticker_ask")
    if ticker_bid is not None and ticker_ask is not None and ticker_bid >= ticker_ask:
        reasons.append("crossed_or_locked_ticker")

    ticker_midpoint = _midpoint(ticker_bid, ticker_ask)
    book_midpoint = _midpoint(order_book.best_bid, order_book.best_ask)
    midpoint_divergence_bps: float | None = None
    if ticker_midpoint is not None and book_midpoint is not None:
        reference = (ticker_midpoint + book_midpoint) / 2.0
        if reference > 0:
            midpoint_divergence_bps = round(
                abs(ticker_midpoint - book_midpoint) / reference * 10_000.0,
                8,
            )
            if midpoint_divergence_bps > divergence_limit:
                reasons.append("cross_source_midpoint_conflict")

    deduplicated_reasons = tuple(dict.fromkeys(reasons))
    if "stale_ticker" in deduplicated_reasons:
        quality = MarketEvidenceQuality.STALE
    elif "cross_source_midpoint_conflict" in deduplicated_reasons:
        quality = MarketEvidenceQuality.CONFLICTING
    elif deduplicated_reasons:
        quality = MarketEvidenceQuality.INVALID
    else:
        quality = MarketEvidenceQuality.FRESH

    return CrossSourceMarketEvidence(
        symbol=symbol,
        source_pair=("bybit_ticker", str(order_book.source or "order_book")),
        ticker_received_at_ms=ticker_received_at_ms,
        evaluated_at_ms=evaluated_at_ms,
        ticker_age_ms=ticker_age_ms,
        ticker_best_bid=ticker_bid,
        ticker_best_ask=ticker_ask,
        ticker_midpoint=ticker_midpoint,
        book_midpoint=book_midpoint,
        midpoint_divergence_bps=midpoint_divergence_bps,
        quality=quality,
        usable_for_decision=quality is MarketEvidenceQuality.FRESH,
        quality_reasons=deduplicated_reasons,
        execution_authority=False,
    )


def _positive_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid >= ask:
        return None
    return (bid + ask) / 2.0


__all__ = [
    "CrossSourceMarketEvidence",
    "MarketEvidenceQuality",
    "evaluate_cross_source_market_evidence",
]
