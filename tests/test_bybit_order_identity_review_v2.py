from __future__ import annotations

import json
import threading

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


def test_quote_coin_spot_fill_uses_executed_value(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    item = intent(category="spot", quantity="500", market_unit="quoteCoin")
    registry.reserve(item, now_ms=NOW)
    registry.update_status(
        item.order_link_id,
        "Filled",
        cum_exec_qty="0.008",
        cum_exec_value="500",
        now_ms=NOW + 1,
    )
    saved = registry.snapshot()["records"][0]
    assert saved["status"] == "Filled"
    assert saved["cum_exec_qty"] == "0.008"
    assert saved["cum_exec_value"] == "500"
    assert registry.snapshot()["restart_safe"] is True


def test_derivative_cancel_accepts_partial_execution_but_blocks_retry(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    item = intent(quantity="1")
    registry.reserve(item, now_ms=NOW)
    registry.update_status(item.order_link_id, "Cancelled", cum_exec_qty="0.4", now_ms=NOW + 1)
    saved = registry.snapshot()["records"][0]
    assert saved["status"] == "Cancelled"
    assert saved["cum_exec_qty"] == "0.4"
    retry = registry.reserve(intent(quantity="1", attempt=2), now_ms=NOW + 2)
    assert retry["safe_to_submit"] is False


def test_same_millisecond_ordered_updates_are_accepted(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    item = intent(quantity="1")
    registry.reserve(item, now_ms=NOW)
    registry.bind_exchange_order(item.order_link_id, "order-001", now_ms=NOW)
    record = registry.update_status(item.order_link_id, "New", now_ms=NOW)
    assert record["status"] == "New"
    record = registry.update_status(
        item.order_link_id,
        "PartiallyFilled",
        cum_exec_qty="0.25",
        now_ms=NOW,
    )
    assert record["cum_exec_qty"] == "0.25"
    assert record["revision"] >= 4


def test_missing_identifiers_and_symbols_fail_before_string_coercion(tmp_path):
    with pytest.raises(ValueError, match="candidate_id is required"):
        intent(candidate_id=None)
    with pytest.raises(ValueError, match="symbol is required"):
        intent(symbol=None)

    registry = OrderIntentRegistry(tmp_path / "intents.json")
    item = intent()
    registry.reserve(item, now_ms=NOW)
    with pytest.raises(ValueError, match="order_id is required"):
        registry.bind_exchange_order(item.order_link_id, None, now_ms=NOW + 1)


def test_fractional_integer_fields_are_rejected():
    with pytest.raises(ValueError, match="whole integer"):
        intent(position_idx=1.9)
    with pytest.raises(ValueError, match="whole integer"):
        intent(attempt=1.2)
    assert intent(position_idx=1.0).position_idx == 1


def test_registry_instances_serialize_duplicate_reservations(tmp_path):
    path = tmp_path / "intents.json"
    registries = [OrderIntentRegistry(path), OrderIntentRegistry(path)]
    barrier = threading.Barrier(2)
    results: list[dict] = []
    errors: list[BaseException] = []

    def worker(registry):
        try:
            barrier.wait(timeout=2)
            results.append(registry.reserve(intent(), now_ms=NOW))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(registry,)) for registry in registries]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert len(results) == 2
    assert sum(result["safe_to_submit"] is True for result in results) == 1
    assert sum(result["must_reconcile"] is True for result in results) == 1
    document = json.loads(path.read_text(encoding="utf-8"))
    assert len(document["records"]) == 1
