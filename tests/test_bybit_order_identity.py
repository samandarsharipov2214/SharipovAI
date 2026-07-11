import json
import re

import pytest

from exchange_connector.bybit_order_identity import OrderIntent, OrderIntentRegistry, build_order_link_id

NOW = 1_700_000_000_000


def intent(**overrides):
    values = {
        "candidate_id": "cand-001",
        "environment": "testnet",
        "category": "spot",
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": "0.0100",
        "attempt": 1,
    }
    values.update(overrides)
    return OrderIntent.create(**values)


def test_order_link_id_is_deterministic_and_bybit_compatible():
    first = build_order_link_id(intent())
    second = build_order_link_id(intent())
    assert first == second
    assert len(first) <= 36
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_business_intent_change_creates_another_identity():
    assert intent().order_link_id != intent(quantity="0.02").order_link_id
    assert intent().order_link_id != intent(attempt=2).order_link_id


def test_first_reservation_is_safe_but_retry_requires_reconciliation(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    first = registry.reserve(intent(), now_ms=NOW)
    retry = registry.reserve(intent(), now_ms=NOW + 1)
    assert first["status"] == "reserved"
    assert first["safe_to_submit"] is True
    assert retry["status"] == "duplicate"
    assert retry["safe_to_submit"] is False
    assert retry["must_reconcile"] is True


def test_reservation_can_bind_only_one_exchange_order(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    link_id = registry.reserve(intent(), now_ms=NOW)["order_link_id"]
    bound = registry.bind_exchange_order(link_id, "123456", now_ms=NOW + 1)
    assert bound["status"] == "accepted"
    assert bound["exchange_order_id"] == "123456"
    assert registry.bind_exchange_order(link_id, "123456", now_ms=NOW + 2)["exchange_order_id"] == "123456"
    with pytest.raises(RuntimeError, match="another"):
        registry.bind_exchange_order(link_id, "999999", now_ms=NOW + 3)


def test_terminal_status_cannot_be_reopened(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    link_id = registry.reserve(intent(), now_ms=NOW)["order_link_id"]
    registry.update_status(link_id, "Filled", now_ms=NOW + 1)
    with pytest.raises(RuntimeError, match="terminal"):
        registry.update_status(link_id, "New", now_ms=NOW + 2)
    assert registry.snapshot()["restart_safe"] is True


def test_unresolved_reservation_blocks_restart_safety(tmp_path):
    registry = OrderIntentRegistry(tmp_path / "intents.json")
    registry.reserve(intent(), now_ms=NOW)
    snapshot = registry.snapshot()
    assert snapshot["restart_safe"] is False
    assert len(snapshot["unresolved_intents"]) == 1


def test_persisted_collision_is_blocked(tmp_path):
    path = tmp_path / "intents.json"
    original = intent()
    link_id = original.order_link_id
    path.write_text(json.dumps({"records": {link_id: {"fingerprint": "different"}}}), encoding="utf-8")
    result = OrderIntentRegistry(path).reserve(original, now_ms=NOW)
    assert result["status"] == "blocked"
    assert result["safe_to_submit"] is False


def test_corrupt_registry_fails_closed(tmp_path):
    path = tmp_path / "intents.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        OrderIntentRegistry(path).snapshot()
