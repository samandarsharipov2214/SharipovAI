from __future__ import annotations

from bybit.order_book_evidence import (
    BookEvidenceQuality,
    BybitSequenceState,
    build_order_book_evidence,
    check_bybit_sequence,
)


def test_snapshot_establishes_sequence_and_gap_fails_closed() -> None:
    initial = check_bybit_sequence(
        BybitSequenceState(), message_type="snapshot", update_id=100
    )
    assert initial.usable is True
    assert initial.state == BybitSequenceState(update_id=100, has_snapshot=True)

    next_delta = check_bybit_sequence(
        initial.state, message_type="delta", update_id=101
    )
    assert next_delta.usable is True
    assert next_delta.state.update_id == 101

    gap = check_bybit_sequence(
        next_delta.state, message_type="delta", update_id=103
    )
    assert gap.usable is False
    assert gap.reason == "update_id_gap"
    assert gap.state == BybitSequenceState()


def test_delta_without_snapshot_and_non_monotonic_update_fail_closed() -> None:
    missing_snapshot = check_bybit_sequence(
        BybitSequenceState(), message_type="delta", update_id=10
    )
    assert missing_snapshot.usable is False
    assert missing_snapshot.reason == "missing_snapshot"

    state = BybitSequenceState(update_id=10, has_snapshot=True)
    duplicate = check_bybit_sequence(state, message_type="delta", update_id=10)
    assert duplicate.usable is False
    assert duplicate.reason == "non_monotonic_update"
    assert duplicate.state == BybitSequenceState()


def test_restart_update_id_one_resets_sequence_baseline() -> None:
    reset = check_bybit_sequence(
        BybitSequenceState(update_id=900, has_snapshot=True),
        message_type="snapshot",
        update_id=1,
    )
    assert reset.usable is True
    assert reset.state == BybitSequenceState(update_id=1, has_snapshot=True)


def test_compact_evidence_calculates_bbo_spread_depth_and_imbalance() -> None:
    evidence = build_order_book_evidence(
        symbol="btcusdt",
        bids=(("100.0", "2"), ("99.5", "3")),
        asks=(("100.5", "1"), ("101.0", "2")),
        observed_at_ms=1_000,
        received_at_ms=1_050,
        update_id=200,
        cross_sequence=7_000,
        max_age_ms=500,
        max_levels=2,
    )

    assert evidence.symbol == "BTCUSDT"
    assert evidence.source == "bybit"
    assert evidence.best_bid == 100.0
    assert evidence.best_ask == 100.5
    assert evidence.spread_bps == 49.87531172
    assert evidence.bid_depth_quote == 498.5
    assert evidence.ask_depth_quote == 302.5
    assert evidence.depth_imbalance == 0.24469413
    assert evidence.quality is BookEvidenceQuality.FRESH
    assert evidence.usable_for_decision is True
    assert evidence.quality_reasons == ()


def test_stale_crossed_invalid_and_sequence_broken_books_never_become_usable() -> None:
    stale = build_order_book_evidence(
        symbol="BTCUSDT",
        bids=((100, 1),),
        asks=((101, 1),),
        observed_at_ms=1_000,
        received_at_ms=4_001,
        update_id=5,
        max_age_ms=2_000,
    )
    assert stale.quality is BookEvidenceQuality.STALE
    assert stale.usable_for_decision is False
    assert "stale_book" in stale.quality_reasons

    crossed = build_order_book_evidence(
        symbol="BTCUSDT",
        bids=((101, 1),),
        asks=((100, 1),),
        observed_at_ms=1_000,
        received_at_ms=1_001,
        update_id=6,
    )
    assert crossed.quality is BookEvidenceQuality.INVALID
    assert crossed.usable_for_decision is False
    assert "crossed_or_locked_book" in crossed.quality_reasons

    sequence_broken = build_order_book_evidence(
        symbol="BTCUSDT",
        bids=((100, 1),),
        asks=((101, 1),),
        observed_at_ms=1_000,
        received_at_ms=1_001,
        update_id=8,
        sequence_usable=False,
        sequence_reason="update_id_gap",
    )
    assert sequence_broken.quality is BookEvidenceQuality.SEQUENCE_GAP
    assert sequence_broken.usable_for_decision is False
    assert "update_id_gap" in sequence_broken.quality_reasons


def test_book_evidence_consumes_only_bounded_levels() -> None:
    consumed = {"bids": 0, "asks": 0}

    def levels(side: str):
        for index in range(1_000_000):
            consumed[side] += 1
            if side == "bids":
                yield (100.0 - index * 0.01, 1.0)
            else:
                yield (101.0 + index * 0.01, 1.0)

    evidence = build_order_book_evidence(
        symbol="BTCUSDT",
        bids=levels("bids"),
        asks=levels("asks"),
        observed_at_ms=1_000,
        received_at_ms=1_001,
        update_id=9,
        max_levels=5,
    )

    assert consumed == {"bids": 5, "asks": 5}
    assert evidence.bid_depth_quote > 0
    assert evidence.ask_depth_quote > 0
    assert evidence.quality is BookEvidenceQuality.FRESH


def test_future_exchange_timestamp_and_bad_level_fail_closed() -> None:
    evidence = build_order_book_evidence(
        symbol="BTCUSDT",
        bids=(("bad", "1"),),
        asks=(("101", "1"),),
        observed_at_ms=2_000,
        received_at_ms=1_000,
        update_id=10,
    )
    assert evidence.quality is BookEvidenceQuality.INVALID
    assert evidence.usable_for_decision is False
    assert "future_exchange_timestamp" in evidence.quality_reasons
    assert "invalid_bid_level" in evidence.quality_reasons
    assert "missing_bid" in evidence.quality_reasons
