import json

import pytest

from exchange_connector.bybit_order_state import BybitOrderStateStore, reconcile_execution_journal

NOW = 1_700_000_000_000


def event(status="New", *, updated=NOW, cum="0", order_id="oid-1", link_id="link-1"):
    return {
        "id": f"msg-{updated}-{status}",
        "topic": "order.spot",
        "creationTime": updated,
        "data": [{
            "category": "spot",
            "orderId": order_id,
            "orderLinkId": link_id,
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderStatus": status,
            "qty": "1",
            "cumExecQty": cum,
            "avgPrice": "60000" if float(cum) else "",
            "createdTime": str(NOW - 100),
            "updatedTime": str(updated),
            "rejectReason": "EC_NoError",
        }],
    }


def test_new_partial_filled_lifecycle_is_persisted(tmp_path):
    store = BybitOrderStateStore(tmp_path / "orders.json")
    assert store.ingest_message(event(), received_at_ms=NOW)["status"] == "ok"
    assert store.ingest_message(event("PartiallyFilled", updated=NOW + 1, cum="0.4"), received_at_ms=NOW + 1)["status"] == "ok"
    assert store.ingest_message(event("Filled", updated=NOW + 2, cum="1"), received_at_ms=NOW + 2)["status"] == "ok"
    snapshot = store.snapshot()
    assert snapshot["tracked_orders"] == 1
    assert snapshot["terminal_orders"][0]["status"] == "Filled"
    assert snapshot["terminal_orders"][0]["cum_exec_qty"] == 1.0


def test_duplicate_filled_event_is_idempotent(tmp_path):
    store = BybitOrderStateStore(tmp_path / "orders.json")
    store.ingest_message(event("Filled", cum="1"), received_at_ms=NOW)
    duplicate = event("Filled", updated=NOW + 1, cum="1")
    result = store.ingest_message(duplicate, received_at_ms=NOW + 1)
    assert result["duplicates"] == ["oid-1"]
    assert result["rejected"] == []


def test_out_of_order_and_cumulative_regression_are_rejected(tmp_path):
    store = BybitOrderStateStore(tmp_path / "orders.json")
    store.ingest_message(event("PartiallyFilled", updated=NOW + 2, cum="0.5"), received_at_ms=NOW + 2)
    older = store.ingest_message(event("New", updated=NOW + 1, cum="0"), received_at_ms=NOW + 3)
    regression = store.ingest_message(event("PartiallyFilled", updated=NOW + 3, cum="0.4"), received_at_ms=NOW + 3)
    assert "out-of-order" in older["rejected"][0]["reason"]
    assert "regression" in regression["rejected"][0]["reason"]
    assert store.snapshot()["orders"][0]["cum_exec_qty"] == 0.5


def test_terminal_state_cannot_return_to_open(tmp_path):
    store = BybitOrderStateStore(tmp_path / "orders.json")
    store.ingest_message(event("Cancelled", cum="0.2"), received_at_ms=NOW)
    result = store.ingest_message(event("New", updated=NOW + 1, cum="0.2"), received_at_ms=NOW + 1)
    assert result["status"] == "blocked"
    assert "terminal" in result["rejected"][0]["reason"]


def test_corrupt_persisted_state_fails_closed(tmp_path):
    path = tmp_path / "orders.json"
    path.write_text("not-json", encoding="utf-8")
    store = BybitOrderStateStore(path)
    with pytest.raises(RuntimeError, match="unreadable"):
        store.snapshot()


def test_reconciliation_marks_unobserved_and_missing_ids():
    journal = {"orders": [
        {"status": "accepted", "order_id": "oid-1"},
        {"status": "accepted", "order_id": "oid-2"},
        {"status": "accepted"},
    ]}
    tracker = {"orders": [{"order_id": "oid-1", "order_link_id": "link-1", "status": "Filled"}]}
    result = reconcile_execution_journal(journal, tracker)
    assert result["status"] == "warning"
    assert result["matched_terminal"] == ["oid-1"]
    assert result["unresolved"][0]["identity"] == "oid-2"
    assert result["missing_identifier_indexes"] == [2]
    assert result["restart_safe"] is False


def test_cancelled_order_may_keep_executed_quantity(tmp_path):
    store = BybitOrderStateStore(tmp_path / "orders.json")
    result = store.ingest_message(event("Cancelled", cum="0.2"), received_at_ms=NOW)
    assert result["status"] == "ok"
    assert store.snapshot()["terminal_orders"][0]["cum_exec_qty"] == 0.2
