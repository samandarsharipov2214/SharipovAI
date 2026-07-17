from __future__ import annotations

import pytest

from exchange_connector.bybit_execution_state import BybitExecutionStateStore
from exchange_connector.bybit_order_state import BybitOrderStateStore
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def _message(*, exec_id: str, qty: str, value: str, fee: str, time_ms: int) -> dict:
    return {
        "id": f"message-{exec_id}",
        "topic": "execution.spot",
        "creationTime": time_ms,
        "data": [
            {
                "category": "spot",
                "execId": exec_id,
                "orderId": "order-1",
                "orderLinkId": "sai_order_1",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "execPrice": "50000",
                "execQty": qty,
                "execValue": value,
                "execFee": fee,
                "feeRate": "0.0006",
                "feeCurrency": "USDT",
                "isMaker": False,
                "execTime": time_ms,
                "seq": time_ms,
            }
        ],
    }


def test_execution_store_aggregates_actual_fees_and_partial_fills(tmp_path) -> None:
    database = _database(tmp_path)
    store = BybitExecutionStateStore(database=database, environment="testnet")

    first = store.ingest_message(
        _message(exec_id="exec-1", qty="0.0002", value="10", fee="0.006", time_ms=1_000_000),
        received_at_ms=1_000_000,
    )
    second = store.ingest_message(
        _message(exec_id="exec-2", qty="0.0003", value="15", fee="0.009", time_ms=1_000_100),
        received_at_ms=1_000_100,
    )

    assert first["accepted_exec_ids"] == ["exec-1"]
    assert second["accepted_exec_ids"] == ["exec-2"]
    aggregate = store.aggregate("sai_order_1")
    assert aggregate is not None
    assert aggregate["execution_count"] == 2
    assert aggregate["filled_quantity"] == pytest.approx(0.0005)
    assert aggregate["executed_value"] == pytest.approx(25.0)
    assert aggregate["actual_fee"] == pytest.approx(0.015)
    assert aggregate["average_fill_price"] == pytest.approx(50_000.0)
    assert aggregate["fee_currencies"] == ["USDT"]


def test_execution_store_deduplicates_exact_replay_and_blocks_conflict(tmp_path) -> None:
    store = BybitExecutionStateStore(database=_database(tmp_path), environment="testnet")
    message = _message(exec_id="exec-1", qty="0.0002", value="10", fee="0.006", time_ms=1_000_000)
    store.ingest_message(message, received_at_ms=1_000_000)

    replay = store.ingest_message(message, received_at_ms=1_000_000)
    assert replay["deduplicated_replays"] == ["exec-1"]

    conflicting = _message(
        exec_id="exec-1",
        qty="0.0002",
        value="10",
        fee="0.007",
        time_ms=1_000_000,
    )
    with pytest.raises(ValueError, match="conflicting private execution identity"):
        store.ingest_message(conflicting, received_at_ms=1_000_000)


def test_execution_reconciliation_detects_missing_and_orphan_fills(tmp_path) -> None:
    database = _database(tmp_path)
    orders = BybitOrderStateStore(database=database, environment="testnet")
    executions = BybitExecutionStateStore(database=database, environment="testnet")
    orders.ingest_message(
        {
            "id": "order-message",
            "topic": "order.spot",
            "creationTime": 1_000_000,
            "data": [
                {
                    "category": "spot",
                    "orderId": "order-1",
                    "orderLinkId": "sai_order_1",
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "orderStatus": "Filled",
                    "qty": "0.0005",
                    "cumExecQty": "0.0005",
                    "avgPrice": "50000",
                    "createdTime": 999_900,
                    "updatedTime": 1_000_000,
                    "rejectReason": "",
                }
            ],
        },
        received_at_ms=1_000_000,
    )
    missing = executions.reconcile(orders.snapshot())
    assert missing["restart_safe"] is False
    assert missing["missing_execution_links"] == ["sai_order_1"]

    executions.ingest_message(
        _message(exec_id="exec-1", qty="0.0005", value="25", fee="0.015", time_ms=1_000_000),
        received_at_ms=1_000_000,
    )
    reconciled = executions.reconcile(orders.snapshot())
    assert reconciled["restart_safe"] is True
    assert reconciled["errors"] == []
