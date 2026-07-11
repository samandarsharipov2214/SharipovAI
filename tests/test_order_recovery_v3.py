from __future__ import annotations

from pathlib import Path

import pytest

from exchange_connector.bybit_order_identity import OrderIntent, OrderIntentRegistry
from exchange_connector.bybit_order_state import BybitOrderStateStore
from storage import ProjectDatabase


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    database.initialize()
    return database


def _message(*, status: str = "New", updated: int = 1_000, executed: str = "0", average: str = "0", order_id: str = "oid-1", link: str = "sai_12345678901234567890123456789012") -> dict:
    return {
        "id": f"msg-{updated}",
        "topic": "order.spot",
        "creationTime": updated,
        "data": [{
            "category": "spot",
            "orderId": order_id,
            "orderLinkId": link,
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderStatus": status,
            "qty": "1",
            "cumExecQty": executed,
            "avgPrice": average,
            "createdTime": "900",
            "updatedTime": str(updated),
        }],
    }


def _intent(*, candidate: str = "candidate-1", attempt: int = 1, quantity: str = "0.1") -> OrderIntent:
    return OrderIntent.create(
        candidate_id=candidate,
        environment="testnet",
        category="spot",
        symbol="BTCUSDT",
        side="Buy",
        order_type="Market",
        quantity=quantity,
        market_unit="quoteCoin",
        attempt=attempt,
    )


def test_order_lifecycle_and_duplicate_filled(tmp_path: Path) -> None:
    store = BybitOrderStateStore(database=_database(tmp_path), environment="testnet")
    assert store.ingest_message(_message(), received_at_ms=1_000)["accepted"]
    partial = _message(status="PartiallyFilled", updated=1_100, executed="0.4", average="60000")
    store.ingest_message(partial, received_at_ms=1_100)
    filled = _message(status="Filled", updated=1_200, executed="1", average="60100")
    store.ingest_message(filled, received_at_ms=1_200)
    duplicate = store.ingest_message(filled, received_at_ms=1_200)
    assert duplicate["duplicates"]
    snapshot = store.snapshot()
    assert snapshot["orders"][0]["status"] == "Filled"
    assert snapshot["open_orders"] == []


def test_replay_future_and_execution_regression_are_blocked(tmp_path: Path) -> None:
    store = BybitOrderStateStore(database=_database(tmp_path), environment="testnet", max_message_lag_seconds=2)
    with pytest.raises(ValueError, match="old or replayed"):
        store.ingest_message(_message(updated=1_000), received_at_ms=4_000)
    with pytest.raises(ValueError, match="future"):
        store.ingest_message(_message(updated=5_000), received_at_ms=1_000)
    store.ingest_message(_message(status="PartiallyFilled", updated=1_000, executed="0.5", average="60000"), received_at_ms=1_000)
    with pytest.raises(ValueError, match="regression"):
        store.ingest_message(_message(status="PartiallyFilled", updated=1_100, executed="0.4", average="60000"), received_at_ms=1_100)


def test_alias_collision_and_terminal_reversal_are_blocked(tmp_path: Path) -> None:
    store = BybitOrderStateStore(database=_database(tmp_path), environment="testnet")
    store.ingest_message(_message(status="Filled", executed="1", average="60000"), received_at_ms=1_000)
    with pytest.raises(ValueError, match="terminal"):
        store.ingest_message(_message(status="New", updated=1_100), received_at_ms=1_100)
    with pytest.raises(RuntimeError, match="different orders|collision"):
        store.ingest_message(_message(order_id="oid-2", updated=1_100), received_at_ms=1_100)


def test_corrupt_database_document_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.put_json("bybit_private_orders", "testnet", {"environment": "testnet", "orders": [], "aliases": {}})
    store = BybitOrderStateStore(database=database, environment="testnet")
    with pytest.raises(RuntimeError, match="structure"):
        store.snapshot()


def test_reconciliation_requires_full_managed_evidence(tmp_path: Path) -> None:
    store = BybitOrderStateStore(database=_database(tmp_path), environment="testnet")
    store.ingest_message(_message(), received_at_ms=1_000)
    blocked = store.reconcile({"orders": []})
    assert blocked["restart_safe"] is False
    row = {
        "status": "accepted",
        "environment": "testnet",
        "category": "spot",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 1,
        "order_id": "oid-1",
        "order_link_id": "sai_12345678901234567890123456789012",
    }
    assert store.reconcile({"orders": [row]})["restart_safe"] is True
    row["quantity"] = 2
    assert store.reconcile({"orders": [row]})["restart_safe"] is False


def test_stable_order_link_id_and_duplicate_reservation(tmp_path: Path) -> None:
    registry = OrderIntentRegistry(database=_database(tmp_path), environment="testnet")
    intent = _intent()
    first = registry.reserve(intent, created_at_ms=1_000)
    second = registry.reserve(intent, created_at_ms=1_001)
    assert first["order_link_id"] == intent.order_link_id()
    assert second["duplicate"] is True
    assert second["requires_reconciliation"] is True
    assert registry.snapshot()["restart_safe"] is False


def test_late_bind_does_not_rollback_ws_state(tmp_path: Path) -> None:
    registry = OrderIntentRegistry(database=_database(tmp_path), environment="testnet")
    link = registry.reserve(_intent(), created_at_ms=1_000)["order_link_id"]
    registry.update_status(link, status="New", cum_exec_qty=0, order_id="oid-1", updated_at_ms=1_100)
    bound = registry.bind_submission(link, order_id="oid-1", updated_at_ms=1_200)
    assert bound["status"] == "New"


def test_partial_execution_blocks_retry(tmp_path: Path) -> None:
    registry = OrderIntentRegistry(database=_database(tmp_path), environment="testnet")
    link = registry.reserve(_intent(), created_at_ms=1_000)["order_link_id"]
    registry.update_status(link, status="PartiallyFilled", cum_exec_qty=0.05, updated_at_ms=1_100)
    registry.update_status(link, status="Cancelled", cum_exec_qty=0.05, updated_at_ms=1_200)
    with pytest.raises(RuntimeError, match="retry is blocked"):
        registry.reserve(_intent(attempt=2), created_at_ms=1_300)


def test_zero_fill_rejected_allows_one_sequential_retry(tmp_path: Path) -> None:
    registry = OrderIntentRegistry(database=_database(tmp_path), environment="testnet")
    link = registry.reserve(_intent(), created_at_ms=1_000)["order_link_id"]
    registry.update_status(link, status="Rejected", cum_exec_qty=0, updated_at_ms=1_100)
    retry = registry.reserve(_intent(attempt=2), created_at_ms=1_200)
    assert retry["attempt"] == 2
    with pytest.raises(RuntimeError, match="sequential"):
        registry.reserve(_intent(attempt=4), created_at_ms=1_300)


def test_intent_affecting_fields_change_identity() -> None:
    base = _intent()
    changed = _intent(quantity="0.2")
    assert base.fingerprint() != changed.fingerprint()
    assert base.order_link_id() != changed.order_link_id()


def test_non_finite_and_unsupported_intents_are_rejected() -> None:
    with pytest.raises(ValueError):
        _intent(quantity="NaN")
    with pytest.raises(ValueError, match="IOC"):
        OrderIntent.create(
            candidate_id="candidate",
            environment="testnet",
            category="spot",
            symbol="BTCUSDT",
            side="Buy",
            order_type="Market",
            quantity="1",
            time_in_force="GTC",
        )
