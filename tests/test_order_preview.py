from __future__ import annotations

import pytest

from exchange_connector.order_preview import OrderPreviewError, build_order_preview


def _payload(**overrides):
    payload = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "quantity": "0.01",
        "reference_price": "60000",
        "limit_price": "60000",
        "stop_loss": "59000",
        "take_profit": "63000",
        "account_equity": "10000",
        "max_risk_percent": "1",
        "leverage": "1",
        "fee_rate": "0.001",
        "slippage_percent": "0.05",
        "tick_size": "0.1",
        "qty_step": "0.001",
        "min_qty": "0.001",
        "min_notional": "5",
    }
    payload.update(overrides)
    return payload


def test_preview_never_executes_and_calculates_risk():
    preview = build_order_preview(_payload())

    assert preview.executable is False
    assert preview.sends_order is False
    assert preview.notional == 600.0
    assert preview.maximum_loss > 0
    assert preview.potential_reward > preview.maximum_loss
    assert preview.risk_percent_of_equity <= 1


def test_quantity_is_rounded_down_to_exchange_step():
    preview = build_order_preview(_payload(quantity="0.0109"))
    assert preview.quantity == 0.01


def test_buy_requires_stop_below_entry_and_take_above():
    with pytest.raises(OrderPreviewError, match="stop_loss < entry_price < take_profit"):
        build_order_preview(_payload(stop_loss="61000"))


def test_preview_blocks_risk_above_limit():
    with pytest.raises(OrderPreviewError, match="maximum risk percent"):
        build_order_preview(_payload(quantity="0.1", max_risk_percent="0.5"))


def test_preview_blocks_below_minimum_notional():
    with pytest.raises(OrderPreviewError, match="notional is below minimum"):
        build_order_preview(_payload(quantity="0.001", limit_price="100", reference_price="100", stop_loss="90", take_profit="120"))


def test_market_preview_applies_directional_slippage():
    buy = build_order_preview(_payload(order_type="market", limit_price=None))
    sell = build_order_preview(
        _payload(
            side="sell",
            order_type="market",
            limit_price=None,
            stop_loss="61000",
            take_profit="57000",
        )
    )

    assert buy.entry_price > 60000
    assert sell.entry_price < 60000
