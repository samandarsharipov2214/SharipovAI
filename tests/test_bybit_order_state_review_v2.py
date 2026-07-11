from __future__ import annotations

from exchange_connector.bybit_order_state import BybitOrderStateStore, reconcile_execution_journal

NOW = 1_800_000_000_000


def event(
    *,
    status="New",
    order_id="oid-1",
    link_id="sai_tl_abc",
    qty="1",
    executed="0",
    category="linear",
    topic="order.linear",
):
    return {
        "id": "msg-review",
        "topic": topic,
        "creationTime": NOW - 50,
        "data": [{
            "category": category,
            "orderId": order_id,
            "orderLinkId": link_id,
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderStatus": status,
            "qty": qty,
            "cumExecQty": executed,
            "avgPrice": "64000" if float(executed) else "",
            "createdTime": NOW - 1000,
            "updatedTime": NOW - 100,
            "rejectReason": "",
        }],
    }


def store(tmp_path, *, environment="testnet", name="orders.json"):
    return BybitOrderStateStore(tmp_path / name, environment=environment)


def journal(*, mode="sandbox", category="linear", order_id="oid-1", link_id="sai_tl_abc"):
    row = {
        "status": "accepted",
        "mode": mode,
        "category": category,
        "order_id": order_id,
        "order_link_id": link_id,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 1,
    }
    return {"orders": [row]}


def test_live_environment_normalizes_to_mainnet(tmp_path):
    state = store(tmp_path, environment="live")
    state.ingest_message(event(), received_at_ms=NOW)
    assert reconcile_execution_journal(journal(mode="live"), state.snapshot())["restart_safe"] is True


def test_both_journal_identifiers_must_resolve_to_same_order(tmp_path):
    state = store(tmp_path)
    state.ingest_message(event(), received_at_ms=NOW)
    result = reconcile_execution_journal(journal(link_id="sai_wrong"), state.snapshot())
    assert result["restart_safe"] is False
    assert "order_link_id" in result["unresolved"][0]["reason"]


def test_triggered_is_instantaneous_closed_not_open(tmp_path):
    state = store(tmp_path)
    state.ingest_message(event(status="Triggered"), received_at_ms=NOW)
    snapshot = state.snapshot()
    assert snapshot["open_orders"] == []
    assert snapshot["instantaneous_closed_orders"][0]["status"] == "Triggered"
    assert reconcile_execution_journal({"orders": []}, snapshot)["restart_safe"] is True


def test_terminal_and_order_id_only_rows_without_journal_are_unresolved(tmp_path):
    state = store(tmp_path)
    state.ingest_message(event(status="Filled", executed="1"), received_at_ms=NOW)
    result = reconcile_execution_journal({"orders": []}, state.snapshot())
    assert result["restart_safe"] is False
    assert "Filled" in result["unresolved"][0]["reason"]

    order_only = store(tmp_path, name="order-only.json")
    order_only.ingest_message(event(order_id="oid-2", link_id=""), received_at_ms=NOW)
    assert reconcile_execution_journal({"orders": []}, order_only.snapshot())["restart_safe"] is False


def test_journal_requires_category_and_managed_order_link_id(tmp_path):
    state = store(tmp_path)
    state.ingest_message(event(), received_at_ms=NOW)
    missing_category = journal()
    missing_category["orders"][0].pop("category")
    result = reconcile_execution_journal(missing_category, state.snapshot())
    assert result["restart_safe"] is False
    assert "category" in result["unresolved"][0]["fields"]

    missing_link = journal()
    missing_link["orders"][0].pop("order_link_id")
    result = reconcile_execution_journal(missing_link, state.snapshot())
    assert result["restart_safe"] is False
    assert "order_link_id" in result["unresolved"][0]["reason"]


def test_category_specific_partial_cancel_statuses(tmp_path):
    linear = store(tmp_path)
    result = linear.ingest_message(event(status="PartiallyFilledCanceled", executed="0.4"), received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "spot" in result["rejected"][0]["reason"]

    spot = store(tmp_path, name="spot.json")
    bad_spot = event(status="Cancelled", executed="0.4", category="spot", topic="order.spot")
    result = spot.ingest_message(bad_spot, received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "PartiallyFilledCanceled" in result["rejected"][0]["reason"]

    good_spot = event(
        status="PartiallyFilledCanceled",
        executed="0.4",
        category="spot",
        topic="order.spot",
    )
    assert spot.ingest_message(good_spot, received_at_ms=NOW)["status"] == "ok"
