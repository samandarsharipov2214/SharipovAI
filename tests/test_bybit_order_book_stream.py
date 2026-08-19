from __future__ import annotations

import pytest

from bybit.order_book_evidence import BookEvidenceQuality
from bybit.order_book_stream import BoundedBybitOrderBook


def _message(*, kind: str, u: int, ts: int = 1_000, bids=(), asks=(), seq: int | None = None):
    return {
        "topic": "orderbook.50.BTCUSDT",
        "type": kind,
        "ts": ts,
        "data": {
            "s": "BTCUSDT",
            "b": list(bids),
            "a": list(asks),
            "u": u,
            "seq": seq if seq is not None else 10_000 + u,
        },
    }


def test_snapshot_then_delta_reconstructs_bbo_and_deletes_zero_size() -> None:
    book = BoundedBybitOrderBook("btcusdt", max_levels=5)
    first = book.apply_message(
        _message(
            kind="snapshot",
            u=100,
            bids=(("100", "2"), ("99", "3")),
            asks=(("101", "4"), ("102", "5")),
        ),
        received_at_ms=1_010,
    )
    assert first.usable_for_decision is True
    assert first.best_bid == 100.0
    assert first.best_ask == 101.0

    updated = book.apply_message(
        _message(
            kind="delta",
            u=101,
            ts=1_020,
            bids=(("100", "0"), ("100.5", "1.5")),
            asks=(("101", "2"), ("103", "1")),
        ),
        received_at_ms=1_030,
    )
    assert updated.usable_for_decision is True
    assert updated.best_bid == 100.5
    assert updated.best_ask == 101.0
    assert book.level_counts == (2, 3)


def test_new_snapshot_replaces_local_book_instead_of_merging() -> None:
    book = BoundedBybitOrderBook("BTCUSDT", max_levels=5)
    book.apply_message(
        _message(kind="snapshot", u=10, bids=(("100", "1"),), asks=(("101", "1"),)),
        received_at_ms=1_000,
    )
    replaced = book.apply_message(
        _message(kind="snapshot", u=50, ts=1_100, bids=(("90", "2"),), asks=(("91", "3"),)),
        received_at_ms=1_100,
    )
    assert replaced.best_bid == 90.0
    assert replaced.best_ask == 91.0
    assert book.level_counts == (1, 1)


def test_delta_before_snapshot_and_sequence_gap_fail_closed_and_reset() -> None:
    book = BoundedBybitOrderBook("BTCUSDT")
    with pytest.raises(ValueError, match="missing_snapshot"):
        book.apply_message(
            _message(kind="delta", u=11, bids=(("100", "1"),), asks=(("101", "1"),)),
            received_at_ms=1_000,
        )

    book.apply_message(
        _message(kind="snapshot", u=20, bids=(("100", "1"),), asks=(("101", "1"),)),
        received_at_ms=1_000,
    )
    with pytest.raises(ValueError, match="update_id_gap"):
        book.apply_message(
            _message(kind="delta", u=22, bids=(("100", "2"),), asks=()),
            received_at_ms=1_000,
        )
    assert book.level_counts == (0, 0)

    with pytest.raises(ValueError, match="missing_snapshot"):
        book.apply_message(
            _message(kind="delta", u=23, bids=(("100", "2"),), asks=()),
            received_at_ms=1_000,
        )


def test_stale_reconstructed_book_is_retained_but_never_decision_usable() -> None:
    book = BoundedBybitOrderBook("BTCUSDT", max_age_ms=100)
    evidence = book.apply_message(
        _message(kind="snapshot", u=1, ts=1_000, bids=(("100", "1"),), asks=(("101", "1"),)),
        received_at_ms=1_500,
    )
    assert evidence.quality is BookEvidenceQuality.STALE
    assert evidence.usable_for_decision is False
    assert "stale_book" in evidence.quality_reasons
    assert book.level_counts == (1, 1)


def test_state_and_emitted_depth_remain_bounded() -> None:
    book = BoundedBybitOrderBook("BTCUSDT", max_levels=3)
    evidence = book.apply_message(
        _message(
            kind="snapshot",
            u=1,
            bids=(("100", "1"), ("99", "1"), ("98", "1"), ("97", "1"), ("96", "1")),
            asks=(("101", "1"), ("102", "1"), ("103", "1"), ("104", "1"), ("105", "1")),
        ),
        received_at_ms=1_000,
    )
    assert book.level_counts == (3, 3)
    assert evidence.levels_per_side == 3
    assert evidence.bid_depth_quote == 297.0
    assert evidence.ask_depth_quote == 306.0


def test_malformed_or_conflicting_message_fails_closed() -> None:
    book = BoundedBybitOrderBook("BTCUSDT")
    with pytest.raises(ValueError, match="symbol"):
        book.apply_message(
            {**_message(kind="snapshot", u=1, bids=(("100", "1"),), asks=(("101", "1"),)), "data": {"s": "ETHUSDT", "b": [["100", "1"]], "a": [["101", "1"]], "u": 1, "seq": 1}},
            received_at_ms=1_000,
        )

    with pytest.raises(ValueError, match="invalid bid level"):
        book.apply_message(
            _message(kind="snapshot", u=1, bids=(("100", "-1"),), asks=(("101", "1"),)),
            received_at_ms=1_000,
        )
