from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_order_state import BybitOrderStateStore, reconcile_execution_journal

NOW = 1_800_000_000_000


def event(
    *,
    status="New",
    order_id="oid-1",
    link_id="sai_tl_abc",
    qty="1",
    executed="0",
    updated=NOW - 100,
    symbol="BTCUSDT",
    category="linear",
    topic="order.linear",
):
    return {
        "id": "msg-1",
        "topic": topic,
        "creationTime": NOW - 50,
        "data": [{
            "category": category,
            "orderId": order_id,
            "orderLinkId": link_id,
            "symbol": symbol,
            "side": "Buy",
            "orderStatus": status,
            "qty": qty,
            "cumExecQty": executed,
            "avgPrice": "64000" if float(executed) else "",
            "createdTime": NOW - 1000,
            "updatedTime": updated,
            "rejectReason": "",
        }],
    }


def store(tmp_path, monkeypatch):
    monkeypatch.setenv("BYBIT_PRIVATE_EVENT_MAX_LAG_SECONDS", "30")
    return BybitOrderStateStore(tmp_path / "orders.json", environment="testnet")


def test_lifecycle_partial_fill_cancel_and_duplicate_terminal(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    assert state.ingest_message(event(), received_at_ms=NOW)["status"] == "ok"
    partial = event(status="PartiallyFilled", executed="0.4", updated=NOW)
    partial["creationTime"] = NOW
    assert state.ingest_message(partial, received_at_ms=NOW)["accepted"]
    cancelled = event(status="Cancelled", executed="0.4", updated=NOW + 100)
    cancelled["creationTime"] = NOW + 100
    assert state.ingest_message(cancelled, received_at_ms=NOW + 100)["accepted"]
    duplicate = state.ingest_message(cancelled, received_at_ms=NOW + 100)
    assert duplicate["duplicates"]
    snapshot = state.snapshot()
    assert snapshot["terminal_orders"][0]["cum_exec_qty"] == 0.4


def test_replay_future_and_stale_row_are_blocked(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    replay = event()
    replay["creationTime"] = NOW - 31_000
    with pytest.raises(ValueError, match="too old"):
        state.ingest_message(replay, received_at_ms=NOW)

    future = event(updated=NOW + 6000)
    future["creationTime"] = NOW
    result = state.ingest_message(future, received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "future" in result["rejected"][0]["reason"]

    wrapped_old_row = event(updated=NOW - 31_000)
    wrapped_old_row["creationTime"] = NOW
    wrapped_old_row["data"][0]["createdTime"] = NOW - 40_000
    result = state.ingest_message(wrapped_old_row, received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "too old" in result["rejected"][0]["reason"]


def test_link_only_same_state_enriches_later_order_id(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    first = event(order_id="", link_id="link-1")
    state.ingest_message(first, received_at_ms=NOW)
    second = event(order_id="oid-1", link_id="link-1", status="New", updated=NOW - 100)
    result = state.ingest_message(second, received_at_ms=NOW)
    assert result["accepted"]
    snapshot = state.snapshot()
    assert snapshot["tracked_orders"] == 1
    assert snapshot["orders"][0]["order_id"] == "oid-1"


def test_later_link_only_event_does_not_erase_order_id(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    state.ingest_message(event(order_id="oid-1", link_id="link-1"), received_at_ms=NOW)
    later = event(order_id="", link_id="link-1", status="PartiallyFilled", executed="0.2", updated=NOW)
    later["creationTime"] = NOW
    state.ingest_message(later, received_at_ms=NOW)
    assert state.snapshot()["orders"][0]["order_id"] == "oid-1"


def test_alias_collision_immutable_mutation_and_topic_mismatch_are_blocked(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    state.ingest_message(event(order_id="oid-1", link_id="link-1"), received_at_ms=NOW)
    state.ingest_message(event(order_id="oid-2", link_id="link-2"), received_at_ms=NOW)

    collision = event(order_id="oid-1", link_id="link-2", updated=NOW)
    collision["creationTime"] = NOW
    assert state.ingest_message(collision, received_at_ms=NOW)["status"] == "blocked"

    mutated = event(
        order_id="oid-1",
        link_id="link-1",
        status="PartiallyFilled",
        executed="0.1",
        updated=NOW,
        symbol="ETHUSDT",
    )
    mutated["creationTime"] = NOW
    result = state.ingest_message(mutated, received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "symbol" in result["rejected"][0]["reason"]

    mismatch = event(category="spot", topic="order.linear")
    result = state.ingest_message(mismatch, received_at_ms=NOW)
    assert result["status"] == "blocked"
    assert "topic" in result["rejected"][0]["reason"]


def test_out_of_order_and_execution_regression_are_blocked(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    partial = event(status="PartiallyFilled", executed="0.5", updated=NOW)
    partial["creationTime"] = NOW
    state.ingest_message(partial, received_at_ms=NOW)

    old = event(status="PartiallyFilled", executed="0.6", updated=NOW - 1)
    old["creationTime"] = NOW
    assert state.ingest_message(old, received_at_ms=NOW)["status"] == "blocked"

    regression = event(status="PartiallyFilled", executed="0.4", updated=NOW + 1)
    regression["creationTime"] = NOW + 1
    assert state.ingest_message(regression, received_at_ms=NOW + 1)["status"] == "blocked"


def test_status_execution_semantics_are_strict(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    invalid_filled = event(status="Filled", executed="0.9")
    assert state.ingest_message(invalid_filled, received_at_ms=NOW)["status"] == "blocked"

    invalid_partial = event(status="PartiallyFilled", executed="0")
    assert state.ingest_message(invalid_partial, received_at_ms=NOW)["status"] == "blocked"

    no_avg = event(status="PartiallyFilled", executed="0.4")
    no_avg["data"][0]["avgPrice"] = ""
    assert state.ingest_message(no_avg, received_at_ms=NOW)["status"] == "blocked"


def test_reconciliation_requires_all_fields_and_no_unknown_open_orders(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    state.ingest_message(event(), received_at_ms=NOW)
    journal = {"orders": [{
        "status": "accepted",
        "mode": "sandbox",
        "category": "linear",
        "order_id": "oid-1",
        "order_link_id": "sai_tl_abc",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 1,
    }]}
    matched = reconcile_execution_journal(journal, state.snapshot())
    assert matched["restart_safe"] is True

    journal["orders"][0]["quantity"] = 2
    blocked = reconcile_execution_journal(journal, state.snapshot())
    assert blocked["restart_safe"] is False
    assert "qty" in blocked["unresolved"][0]["fields"]

    empty_journal = reconcile_execution_journal({"orders": []}, state.snapshot())
    assert empty_journal["restart_safe"] is False
    assert "missing from execution journal" in empty_journal["unresolved"][0]["reason"]


def test_missing_or_mismatched_environment_blocks_restart(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    state.ingest_message(event(), received_at_ms=NOW)
    bad = {"orders": [{
        "status": "accepted",
        "mode": "live",
        "category": "linear",
        "order_id": "oid-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 1,
    }]}
    result = reconcile_execution_journal(bad, state.snapshot())
    assert result["restart_safe"] is False
    assert "environment" in result["unresolved"][0]["fields"]


def test_corrupt_storage_and_alias_targets_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "orders.json"
    path.write_text("{broken", encoding="utf-8")
    state = BybitOrderStateStore(path, environment="testnet")
    with pytest.raises(RuntimeError, match="unreadable"):
        state.snapshot()

    path.write_text(
        json.dumps({"orders": {}, "aliases": {"order:oid": "order:missing"}, "updated_at_ms": NOW}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="aliases"):
        state.snapshot()


def test_persisted_alias_document_is_atomic_and_structured(tmp_path, monkeypatch):
    state = store(tmp_path, monkeypatch)
    state.ingest_message(event(), received_at_ms=NOW)
    document = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    assert document["aliases"]["order:oid-1"] == document["aliases"]["link:sai_tl_abc"]
    assert len(document["orders"]) == 1
