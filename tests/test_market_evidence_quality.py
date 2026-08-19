from __future__ import annotations

from bybit.market_evidence_quality import (
    MarketEvidenceQuality,
    evaluate_cross_source_market_evidence,
)
from bybit.models import TickerInfo
from bybit.order_book_evidence import build_order_book_evidence


def _book(*, received_at_ms: int = 1_000, observed_at_ms: int = 950, bid: float = 100.0, ask: float = 101.0):
    return build_order_book_evidence(
        symbol="BTCUSDT",
        bids=((bid, 2.0), (99.5, 1.0)),
        asks=((ask, 2.0), (101.5, 1.0)),
        observed_at_ms=observed_at_ms,
        received_at_ms=received_at_ms,
        update_id=10,
        cross_sequence=20,
        max_age_ms=2_000,
        max_levels=10,
        sequence_usable=True,
    )


def _ticker(*, bid: str = "100", ask: str = "101", symbol: str = "BTCUSDT") -> TickerInfo:
    return TickerInfo(
        category="spot",
        symbol=symbol,
        last_price="100.5",
        bid_price=bid,
        ask_price=ask,
    )


def test_fresh_aligned_sources_are_usable_without_execution_authority() -> None:
    evidence = evaluate_cross_source_market_evidence(
        ticker=_ticker(),
        order_book=_book(),
        ticker_received_at_ms=1_000,
        evaluated_at_ms=1_100,
    )

    assert evidence.quality is MarketEvidenceQuality.FRESH
    assert evidence.usable_for_decision is True
    assert evidence.quality_reasons == ()
    assert evidence.execution_authority is False
    assert evidence.midpoint_divergence_bps == 0.0


def test_stale_ticker_fails_closed() -> None:
    evidence = evaluate_cross_source_market_evidence(
        ticker=_ticker(),
        order_book=_book(),
        ticker_received_at_ms=1_000,
        evaluated_at_ms=3_001,
        max_ticker_age_ms=2_000,
    )

    assert evidence.quality is MarketEvidenceQuality.STALE
    assert evidence.usable_for_decision is False
    assert "stale_ticker" in evidence.quality_reasons


def test_material_cross_source_midpoint_conflict_fails_closed() -> None:
    evidence = evaluate_cross_source_market_evidence(
        ticker=_ticker(bid="103", ask="104"),
        order_book=_book(),
        ticker_received_at_ms=1_000,
        evaluated_at_ms=1_100,
        max_midpoint_divergence_bps=25.0,
    )

    assert evidence.quality is MarketEvidenceQuality.CONFLICTING
    assert evidence.usable_for_decision is False
    assert evidence.midpoint_divergence_bps is not None
    assert evidence.midpoint_divergence_bps > 25.0
    assert "cross_source_midpoint_conflict" in evidence.quality_reasons


def test_stale_order_book_propagates_stale_fail_closed_quality() -> None:
    stale_book = _book(received_at_ms=5_000, observed_at_ms=1_000)
    evidence = evaluate_cross_source_market_evidence(
        ticker=_ticker(),
        order_book=stale_book,
        ticker_received_at_ms=4_900,
        evaluated_at_ms=5_000,
    )

    assert evidence.quality is MarketEvidenceQuality.STALE
    assert evidence.usable_for_decision is False
    assert "order_book_unusable" in evidence.quality_reasons
    assert "order_book:stale_book" in evidence.quality_reasons


def test_symbol_mismatch_and_crossed_ticker_fail_closed() -> None:
    evidence = evaluate_cross_source_market_evidence(
        ticker=_ticker(symbol="ETHUSDT", bid="101", ask="100"),
        order_book=_book(),
        ticker_received_at_ms=1_000,
        evaluated_at_ms=1_100,
    )

    assert evidence.quality is MarketEvidenceQuality.INVALID
    assert evidence.usable_for_decision is False
    assert "symbol_mismatch" in evidence.quality_reasons
    assert "crossed_or_locked_ticker" in evidence.quality_reasons


def test_future_receipt_and_invalid_quote_fail_closed() -> None:
    evidence = evaluate_cross_source_market_evidence(
        ticker=_ticker(bid="nan", ask="101"),
        order_book=_book(),
        ticker_received_at_ms=1_101,
        evaluated_at_ms=1_100,
    )

    assert evidence.quality is MarketEvidenceQuality.INVALID
    assert evidence.usable_for_decision is False
    assert "future_ticker_receipt" in evidence.quality_reasons
    assert "invalid_ticker_bid" in evidence.quality_reasons


def test_configuration_validation_rejects_invalid_limits() -> None:
    try:
        evaluate_cross_source_market_evidence(
            ticker=_ticker(),
            order_book=_book(),
            ticker_received_at_ms=1_000,
            evaluated_at_ms=1_100,
            max_midpoint_divergence_bps=float("inf"),
        )
    except ValueError as exc:
        assert "max_midpoint_divergence_bps" in str(exc)
    else:  # pragma: no cover - proof that invalid configuration cannot pass silently
        raise AssertionError("expected ValueError")
