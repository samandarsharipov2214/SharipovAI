from __future__ import annotations

import json

import pytest

from exchange_connector.bybit_order_identity import OrderIntent, OrderIntentRegistry

NOW = 1_800_000_000_000


def intent(**changes):
    values = {
        "candidate_id": "candidate-001",
        "environment": "testnet",
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "order_type": "Market",
        "quantity": "0.01",
        "time_in_force": "IOC",
        "reduce_only": False,
        "position_idx": 0,
        "market_unit": "",
        "attempt": 1,
    }
    values.update(changes)
    return OrderIntent.create(**values)


def test_complete_intent_generates_stable_bybit_id():
    first = intent()
    second = intent(quantity="0.0100")
    assert first.order_link_id == second.order_link_id
    assert len(first.order_link_id) <= 36
    assert first.order_link_id.replace("_", "").isalnum()


def test_supported_execution_fields_change_identity():
    base = intent().order_link_id
    variants = [
        intent(quantity="0.02"),
        intent(side="Sell"),
        intent(order_type="Limit", price="64000", time_in_force="GTC"),
        intent(reduce_only=True),
        intent(position_idx=1),
        intent(category="spot", market_unit="quoteCoin"),
    ]
    assert all(item.order_link_id != base for item in variants)
    assert len({item.order_link_id for item in variants}) == len(variants)


def test_order_shape_and_unsupported_features_fail_closed():
    with pytest.raises(ValueError, match="must not include price"):
        intent(price="64000")
    with pytest.raises(ValueError, match="requires price"):
        intent(order_type="Limit", time_in_force="GTC")
    with pytest.raises(ValueError, match="conditional orders"):
        intent(trigger_price="63000")
    with pytest.raises(ValueError, match="time_in_force must be IOC"):
        intent(time_in_force="GTC")
    with pytest.raises(ValueError, match="market_unit"):
        intent(market_unit="quoteCoin")
    with pytest.raises(ValueError, match="reduce_only"):
        intent(category="spot", reduce_only=True)
    with pytest.raises(ValueError, match="position_idx=0"):
        intent(category="spot", position_idx=1)
    with pytest.raises(ValueError, match="must not include market_unit"):
        intent(category="spot", order_type="Limit", price="64000", market_unit="quoteCoin")
    assert intent(category="spot", side="Buy").market_unit == "quoteCoin"
    assert intent(category="spot", side="Sell").market_unit == "baseCoin"


def test_duplicate_reservation_requires_reconciliation(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    first = registry.reserve(intent(), now_ms=NOW)
    second = registry.reserve(intent(), now_ms=NOW + 1)
    assert first["safe_to_submit"] is True
    assert second["safe_to_submit"] is False
    assert second["must_reconcile"] is True


def test_new_attempt_requires_zero_execution_terminal_previous_attempt(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    registry.reserve(intent(), now_ms=NOW)
    blocked = registry.reserve(intent(attempt=2), now_ms=NOW + 1)
    assert blocked["status"] == "blocked"
    registry.update_status(intent().order_link_id, "Rejected", now_ms=NOW + 2)
    assert registry.reserve(intent(attempt=2), now_ms=NOW + 3)["safe_to_submit"] is True

    other = OrderIntentRegistry(tmp_path / "partial.json")
    other.reserve(intent(), now_ms=NOW)
    other.update_status(intent().order_link_id, "PartiallyFilled", cum_exec_qty="0.004", now_ms=NOW + 1)
    other.update_status(intent().order_link_id, "Cancelled", cum_exec_qty="0.004", now_ms=NOW + 2)
    partial_retry = other.reserve(intent(attempt=2), now_ms=NOW + 3)
    assert partial_retry["safe_to_submit"] is False
    assert "without execution" in partial_retry["reason"]


def test_websocket_status_can_arrive_before_rest_binding(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    link = intent().order_link_id
    registry.reserve(intent(), now_ms=NOW)
    registry.update_status(link, "New", now_ms=NOW + 1)
    bound = registry.bind_exchange_order(link, "order-001", now_ms=NOW + 2)
    assert bound["status"] == "New"
    assert bound["exchange_order_id"] == "order-001"


def test_order_binding_uniqueness_and_status_transitions_are_strict(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    link = intent().order_link_id
    registry.reserve(intent(), now_ms=NOW)
    submitted = registry.bind_exchange_order(link, "order-001", now_ms=NOW + 1)
    assert submitted["status"] == "Submitted"
    with pytest.raises(RuntimeError, match="another orderId"):
        registry.bind_exchange_order(link, "order-002", now_ms=NOW + 2)

    second = intent(candidate_id="candidate-002")
    registry.reserve(second, now_ms=NOW + 3)
    with pytest.raises(RuntimeError, match="another reservation"):
        registry.bind_exchange_order(second.order_link_id, "order-001", now_ms=NOW + 4)

    registry.update_status(link, "New", now_ms=NOW + 5)
    registry.update_status(link, "PartiallyFilled", cum_exec_qty="0.004", now_ms=NOW + 6)
    registry.update_status(link, "Filled", cum_exec_qty="0.01", now_ms=NOW + 7)
    with pytest.raises(RuntimeError, match="terminal"):
        registry.update_status(link, "New", cum_exec_qty="0.01", now_ms=NOW + 8)
    with pytest.raises(ValueError, match="status must be"):
        registry.update_status(link, "MadeUp", now_ms=NOW + 9)


def test_status_execution_semantics_and_timestamp_are_strict(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    link = intent().order_link_id
    registry.reserve(intent(), now_ms=NOW)
    with pytest.raises(ValueError, match="partial"):
        registry.update_status(link, "PartiallyFilled", cum_exec_qty="0", now_ms=NOW + 1)
    registry.bind_exchange_order(link, "order-001", now_ms=NOW + 10)
    with pytest.raises(RuntimeError, match="timestamp regressed"):
        registry.update_status(link, "New", now_ms=NOW + 5)


def test_unresolved_reservation_blocks_restart(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    registry.reserve(intent(), now_ms=NOW)
    assert registry.snapshot()["restart_safe"] is False
    registry.update_status(intent().order_link_id, "Cancelled", cum_exec_qty="0", now_ms=NOW + 1)
    assert registry.snapshot()["restart_safe"] is True


def test_corrupt_or_tampered_storage_fails_closed(tmp_path):
    path = tmp_path / "intents.json"
    path.write_text("not-json", encoding="utf-8")
    registry = OrderIntentRegistry(path)
    with pytest.raises(RuntimeError, match="unreadable"):
        registry.snapshot()

    path.unlink()
    full = intent(order_type="Limit", price="64000", time_in_force="GTC", reduce_only=True, position_idx=1)
    registry.reserve(full, now_ms=NOW)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][full.order_link_id]["intent"]["quantity"] = "999"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match"):
        registry.snapshot()


def test_persisted_record_contains_canonical_supported_intent(tmp_path):
    path = tmp_path / "intents.json"
    registry = OrderIntentRegistry(path)
    full = intent(order_type="Limit", price="64000", time_in_force="GTC", reduce_only=True, position_idx=1)
    registry.reserve(full, now_ms=NOW)
    document = json.loads(path.read_text(encoding="utf-8"))
    saved = document["records"][full.order_link_id]
    assert saved["intent"]["price"] == "64000"
    assert saved["intent"]["trigger_price"] == ""
    assert saved["cum_exec_qty"] == "0"
    assert saved["cum_exec_value"] == "0"
    assert saved["fingerprint"] == full.fingerprint
