from __future__ import annotations

import pytest

from exchange_connector.bybit_private_order_ws import _validate_subscribe_ack


def test_private_ws_requires_order_and_execution_topics() -> None:
    _validate_subscribe_ack(
        {
            "op": "subscribe",
            "success": True,
            "req_id": "sharipovai-private-order-execution",
            "ret_msg": "",
            "data": {
                "successTopics": ["order", "execution"],
                "failTopics": [],
            },
        }
    )

    with pytest.raises(RuntimeError, match="missing topics: execution"):
        _validate_subscribe_ack(
            {
                "op": "subscribe",
                "success": True,
                "req_id": "sharipovai-private-order-execution",
                "ret_msg": "",
                "data": {
                    "successTopics": ["order"],
                    "failTopics": [],
                },
            }
        )


def test_private_ws_blocks_any_failed_topic() -> None:
    with pytest.raises(RuntimeError, match="private subscription failed"):
        _validate_subscribe_ack(
            {
                "op": "subscribe",
                "success": True,
                "req_id": "sharipovai-private-order-execution",
                "data": {
                    "successTopics": ["order"],
                    "failTopics": ["execution"],
                },
            }
        )
