from __future__ import annotations

from pathlib import Path

import pytest

from exchange_connector.bybit_order_identity import OrderIntent, OrderIntentRegistry
from exchange_connector.bybit_order_state import BybitOrderStateStore
from storage import ProjectDatabase

LINK = "sai_12345678901234567890123456789012"


def db(tmp_path: Path) -> ProjectDatabase:
    value = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    value.initialize()
    return value


def message(status="New", updated=1000, executed="0", average="0", order_id="oid-1", link=LINK):
    return {
        "id": f"msg-{updated}", "topic": "order.spot", "creationTime": updated,
        "data": [{
            "category": "spot", "orderId": order_id, "orderLinkId": link,
            "symbol": "BTCUSDT", "side": "Buy", "orderStatus": status,
            "qty": "1", "cumExecQty": executed, "avgPrice": average,
            "createdTime": "900", "updatedTime": str(updated),
        }],
    }


def intent(attempt=1, quantity="0.1") -> OrderIntent:
    return OrderIntent.create(
        candidate_id="candidate-1", environment="testnet", category="spot",
        symbol="BTCUSDT", side="Buy", order_type="Market",
        quantity=quantity, market_unit="quoteCoin", attempt=attempt,
    )


def test_lifecycle_duplicate_and_replay_protection(tmp_path: Path) -> None:
    store = BybitOrderStateStore(database=db(tmp_path), environment="testnet", max_message_lag_seconds=2)
    store.ingest_message(message(), received_at_ms=1000)
    store.ingest_message(message("PartiallyFilled", 1100, "0.4", "60000"), received_at_ms=1100)
    filled = message("Filled", 1200, "1", "60100")
    store.ingest_message(filled, received_at_ms=1200)
    assert store.ingest_message(filled, received_at_ms=1200)["duplicates"]
    assert store.snapshot()["open_orders"] == []
    with pytest.raises(ValueError, match="old or replayed"):
        store.ingest_message(message(updated=1000), received_at_ms=4000)


def test_future_regression_terminal_and_alias_conflicts_block(tmp_path: Path) -> None:
    store = BybitOrderStateStore(database=db(tmp_path), environment="testnet")
    with pytest.raises(ValueError, match="future"):
        store.ingest_message(message(updated=5000), received_at_ms=1000)
    store.ingest_message(message("PartiallyFilled", 1000, "0.5", "60000"), received_at_ms=1000)
    with pytest.raises(ValueError, match="regression"):
        store.ingest_message(message("PartiallyFilled", 1100, "0.4", "60000"), received_at_ms=1100)
    store.ingest_message(message("Filled", 1200, "1", "60000"), received_at_ms=1200)
    with pytest.raises(ValueError, match="terminal"):
        store.ingest_message(message("New", 1300), received_at_ms=1300)
    with pytest.raises((RuntimeError, ValueError), match="different orders|collision|orderId changed"):
        store.ingest_message(message("New", 1300, order_id="oid-2"), received_at_ms=1300)


def test_corruption_and_missing_journal_evidence_fail_closed(tmp_path: Path) -> None:
    database = db(tmp_path)
    store = BybitOrderStateStore(database=database, environment="testnet")
    store.ingest_message(message(), received_at_ms=1000)
    assert store.reconcile({"orders": []})["restart_safe"] is False
    good = {
        "status": "accepted", "environment": "testnet", "category": "spot",
        "symbol": "BTCUSDT", "side": "BUY", "quantity": 1,
        "order_id": "oid-1", "order_link_id": LINK,
    }
    assert store.reconcile({"orders": [good]})["restart_safe"] is True
    good["quantity"] = 2
    assert store.reconcile({"orders": [good]})["restart_safe"] is False
    database.put_json("bybit_private_orders", "testnet", {"environment": "testnet", "orders": [], "aliases": {}}, expected_version=1)
    with pytest.raises(RuntimeError, match="structure"):
        store.snapshot()


def test_stable_reservation_and_late_rest_bind(tmp_path: Path) -> None:
    registry = OrderIntentRegistry(database=db(tmp_path), environment="testnet")
    first = registry.reserve(intent(), created_at_ms=1000)
    duplicate = registry.reserve(intent(), created_at_ms=1001)
    assert first["order_link_id"] == intent().order_link_id()
    assert duplicate["requires_reconciliation"] is True
    link = first["order_link_id"]
    registry.update_status(link, status="New", cum_exec_qty=0, order_id="oid-1", updated_at_ms=1100)
    assert registry.bind_submission(link, order_id="oid-1", updated_at_ms=1200)["status"] == "New"


def test_partial_fill_blocks_retry_but_zero_fill_rejection_allows_one(tmp_path: Path) -> None:
    registry = OrderIntentRegistry(database=db(tmp_path), environment="testnet")
    link = registry.reserve(intent(), created_at_ms=1000)["order_link_id"]
    registry.update_status(link, status="PartiallyFilled", cum_exec_qty=0.05, updated_at_ms=1100)
    registry.update_status(link, status="Cancelled", cum_exec_qty=0.05, updated_at_ms=1200)
    with pytest.raises(RuntimeError, match="retry is blocked"):
        registry.reserve(intent(attempt=2), created_at_ms=1300)

    second = OrderIntentRegistry(database=db(tmp_path / "other"), environment="testnet")
    second_link = second.reserve(intent(), created_at_ms=1000)["order_link_id"]
    second.update_status(second_link, status="Rejected", cum_exec_qty=0, updated_at_ms=1100)
    assert second.reserve(intent(attempt=2), created_at_ms=1200)["attempt"] == 2
    with pytest.raises(RuntimeError, match="sequential"):
        second.reserve(intent(attempt=4), created_at_ms=1300)


def test_intent_identity_covers_execution_fields_and_rejects_nonfinite() -> None:
    assert intent().order_link_id() != intent(quantity="0.2").order_link_id()
    with pytest.raises(ValueError):
        intent(quantity="NaN")
    with pytest.raises(ValueError, match="IOC"):
        OrderIntent.create(
            candidate_id="candidate", environment="testnet", category="spot",
            symbol="BTCUSDT", side="Buy", order_type="Market", quantity="1",
            time_in_force="GTC",
        )
