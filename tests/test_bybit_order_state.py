from __future__ import annotations

import json
import time

import pytest

from exchange_connector.bybit_order_state import (
    BybitOrderStateStore,
    reconcile_execution_journal,
)

NOW = int(time.time() * 1000)


def _order(
    *,
    status: str = "New",
    order_id: str = "order-001",
    link_id: str = "sai_test_001",
    qty: str = "1",
    cum: str = "0",
    avg: str = "",
    created: int = NOW - 100,
    updated: int = NOW,
    **changes,
):
    item = {
        "orderId": order_id,
        "orderLinkId": link_id,
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "orderStatus": status,
        "qty": qty,
        "cumExecQty": cum,
        "avgPrice": avg,
        "rejectReason": "EC_NoError",
        "createdTime": str(created),
        "updatedTime": str(updated),
    }
    item.update(changes)
    return item


def _message(item, *, creation: int | None = None, message_id: str = "msg-001"):
    return {
        "id": message_id,
        "topic": "order.linear",
        "creationTime": creation if creation is not None else int(item["updatedTime"]),
        "data": [item],
    }


def _ingest(store, item, *, received: int | None = None, message_id: str = "msg-001"):
    timestamp = int(item["updatedTime"])
    return store.ingest_message(
        _message(item, creation=timestamp, message_id=message_id),
        received_at_ms=timestamp if received is None else received,
    )


def test_new_partial_filled_lifecycle_and_duplicate_filled(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    assert _ingest(store, _order(updated=NOW), message_id="m1")["status"] == "ok"
    assert _ingest(
        store,
        _order(status="PartiallyFilled", cum="0.4", avg="100", updated=NOW + 100),
        message_id="m2",
    )["status"] == "ok"
    assert _ingest(
        store,
        _order(status="Filled", cum="1", avg="101", updated=NOW + 200),
        message_id="m3",
    )["status"] == "ok"

    duplicate = _ingest(
        store,
        _order(status="Filled", cum="1", avg="101", updated=NOW + 300),
        message_id="m4",
    )
    assert duplicate["status"] == "ok"
    assert duplicate["accepted"] == []
    assert duplicate["duplicates"] == ["order-001"]
    snapshot = store.snapshot()
    assert snapshot["tracked_orders"] == 1
    assert snapshot["terminal_orders"][0]["status"] == "Filled"


def test_order_link_only_record_is_enriched_without_duplication(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    first = _order(order_id="", updated=NOW)
    second = _order(order_id="order-001", updated=NOW + 10)
    assert _ingest(store, first, message_id="m1")["accepted"] == ["link:sai_test_001"]
    assert _ingest(store, second, message_id="m2")["accepted"] == ["link:sai_test_001"]

    snapshot = store.snapshot()
    assert snapshot["tracked_orders"] == 1
    tracked = snapshot["orders"][0]
    assert tracked["order_id"] == "order-001"
    assert tracked["order_link_id"] == "sai_test_001"


def test_identifiers_cannot_resolve_to_two_different_orders(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    _ingest(store, _order(order_id="order-001", link_id="link-001", updated=NOW), message_id="m1")
    _ingest(
        store,
        _order(order_id="order-002", link_id="link-002", updated=NOW + 10),
        message_id="m2",
    )
    result = _ingest(
        store,
        _order(order_id="order-001", link_id="link-002", updated=NOW + 20),
        message_id="m3",
    )
    assert result["status"] == "blocked"
    assert "resolve to different" in result["rejected"][0]["reason"]
    assert store.snapshot()["tracked_orders"] == 2


def test_stale_future_and_non_finite_events_fail_closed(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    stale = _order(created=NOW - 20_000, updated=NOW - 20_000)
    with pytest.raises(ValueError, match="stale"):
        store.ingest_message(_message(stale), received_at_ms=NOW)

    future = _order(updated=NOW + store.max_future_skew_ms + 1)
    result = store.ingest_message(_message(future, creation=NOW), received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "future" in result["rejected"][0]["reason"]

    invalid = _order(qty="nan", updated=NOW)
    result = _ingest(store, invalid)
    assert result["status"] == "blocked"
    assert "finite" in result["rejected"][0]["reason"]


def test_out_of_order_regression_and_terminal_reversal_are_blocked(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    _ingest(store, _order(updated=NOW), message_id="m1")
    _ingest(
        store,
        _order(status="PartiallyFilled", cum="0.5", avg="100", updated=NOW + 100),
        message_id="m2",
    )

    out_of_order = _ingest(
        store,
        _order(status="PartiallyFilled", cum="0.6", avg="100", updated=NOW + 50),
        message_id="m3",
        received=NOW + 100,
    )
    assert "out-of-order" in out_of_order["rejected"][0]["reason"]

    regression = _ingest(
        store,
        _order(status="PartiallyFilled", cum="0.4", avg="100", updated=NOW + 200),
        message_id="m4",
    )
    assert "regression" in regression["rejected"][0]["reason"]

    _ingest(
        store,
        _order(status="Filled", cum="1", avg="101", updated=NOW + 300),
        message_id="m5",
    )
    reversal = _ingest(store, _order(status="New", updated=NOW + 400), message_id="m6")
    assert "terminal" in reversal["rejected"][0]["reason"]


def test_cancelled_order_keeps_partial_execution(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    _ingest(store, _order(updated=NOW), message_id="m1")
    result = _ingest(
        store,
        _order(status="Cancelled", cum="0.25", avg="100", updated=NOW + 100),
        message_id="m2",
    )
    assert result["status"] == "ok"
    tracked = store.snapshot()["terminal_orders"][0]
    assert tracked["status"] == "Cancelled"
    assert tracked["cum_exec_qty"] == 0.25


def test_corrupt_persistent_state_fails_closed(tmp_path) -> None:
    path = tmp_path / "orders.json"
    path.write_text("{broken", encoding="utf-8")
    store = BybitOrderStateStore(path, environment="testnet")
    with pytest.raises(RuntimeError, match="unreadable"):
        store.snapshot()


def test_matching_journal_and_private_state_are_restart_safe(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    _ingest(store, _order(updated=NOW), message_id="m1")
    journal = {
        "orders": [
            {
                "status": "accepted",
                "order_id": "order-001",
                "order_link_id": "sai_test_001",
                "environment": "testnet",
                "category": "linear",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "quantity": 1,
            }
        ]
    }
    result = reconcile_execution_journal(journal, store.snapshot())
    assert result["status"] == "ok"
    assert result["restart_safe"] is True
    assert result["matched_open"] == ["order-001"]


def test_missing_mismatched_and_malformed_journal_fields_block_restart(tmp_path) -> None:
    store = BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")
    _ingest(store, _order(updated=NOW), message_id="m1")
    base = {
        "status": "accepted",
        "order_id": "order-001",
        "order_link_id": "sai_test_001",
        "environment": "testnet",
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "quantity": 1,
    }
    cases = [
        {key: value for key, value in base.items() if key != "quantity"},
        {**base, "environment": "mainnet"},
        {**base, "category": "spot"},
        {**base, "symbol": "ETHUSDT"},
        {**base, "side": "Sell"},
        {**base, "quantity": 2},
        {**base, "quantity": "not-a-number"},
    ]
    for item in cases:
        result = reconcile_execution_journal({"orders": [item]}, store.snapshot())
        assert result["restart_safe"] is False
        assert result["unresolved"]


def test_invalid_or_duplicate_tracker_snapshot_blocks_restart() -> None:
    journal = {"orders": []}
    invalid = reconcile_execution_journal(journal, {"orders": "broken"})
    assert invalid["restart_safe"] is False

    tracked = _order(updated=NOW)
    normalized = {
        "order_id": "order-001",
        "order_link_id": "sai_test_001",
        "environment": "testnet",
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "status": "New",
        "qty": 1,
    }
    duplicate = reconcile_execution_journal(journal, {"orders": [normalized, dict(normalized)]})
    assert duplicate["restart_safe"] is False
    assert any("duplicate" in item["reason"] for item in duplicate["unresolved"])
