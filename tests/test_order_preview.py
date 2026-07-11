from __future__ import annotations

from decimal import Decimal

import pytest

from exchange_connector.bybit_instrument_rules import BybitInstrumentRules
from exchange_connector.order_preview import OrderPreviewError, build_order_preview


def _rules(category: str = "linear") -> BybitInstrumentRules:
    derivative = category == "linear"
    return BybitInstrumentRules(
        symbol="BTCUSDT",
        category=category,
        status="Trading",
        base_coin="BTC",
        quote_coin="USDT",
        tick_size=Decimal("0.1"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        max_limit_qty=Decimal("100"),
        max_market_qty=Decimal("50"),
        min_price=Decimal("1"),
        max_price=Decimal("1000000"),
        min_leverage=Decimal("1") if derivative else None,
        max_leverage=Decimal("20") if derivative else None,
        leverage_step=Decimal("0.5") if derivative else None,
        fetched_at_ms=123456789,
    )


def _payload(**changes):
    payload = {
        "symbol": "BTCUSDT",
        "category": "linear",
        "side": "buy",
        "order_type": "market",
        "quantity": "1",
        "reference_price": "100",
        "stop_loss": "90",
        "take_profit": "120",
        "account_equity": "10000",
        "available_balance": "1000",
        "leverage": "10",
        "fee_rate": "0.001",
        "exit_fee_rate": "0.001",
        "slippage_percent": "1",
        "max_risk_percent": "1",
    }
    payload.update(changes)
    return payload


def test_market_preview_reports_slippage_without_double_counting() -> None:
    preview = build_order_preview(_payload(), _rules())
    assert preview.entry_price == 101.0
    assert preview.estimated_slippage == 1.0
    assert preview.maximum_loss == pytest.approx(11.191)
    assert preview.maximum_loss < 12
    assert preview.potential_reward == pytest.approx(18.779)
    assert preview.required_capital == pytest.approx(10.201)
    assert preview.risk_approved is False
    assert preview.executable is False
    assert preview.executed is False
    assert preview.sends_order is False
    assert preview.funding_included is False
    assert preview.liquidation_checked is False


def test_limit_rounding_is_conservative() -> None:
    preview = build_order_preview(
        _payload(
            order_type="limit",
            limit_price="100.09",
            slippage_percent="0",
            stop_loss="89.99",
            take_profit="120.09",
        ),
        _rules(),
    )
    assert preview.entry_price == 100.0
    assert preview.stop_loss == 89.9
    assert preview.take_profit == 120.0
    assert preview.estimated_slippage == 0


def test_manual_instrument_rule_override_is_blocked() -> None:
    for field in ("tick_size", "qty_step", "min_notional", "max_leverage"):
        with pytest.raises(OrderPreviewError, match="cannot be supplied"):
            build_order_preview(_payload(**{field: "999"}), _rules())


def test_verified_quantity_notional_price_and_leverage_limits_are_enforced() -> None:
    cases = [
        _payload(quantity="0.0001"),
        _payload(quantity="51"),
        _payload(quantity="0.01", reference_price="100", stop_loss="90", take_profit="120"),
        _payload(leverage="20.1"),
        _payload(leverage="10.25"),
        _payload(reference_price="2000000", stop_loss="1999999", take_profit="2000001"),
    ]
    for payload in cases:
        with pytest.raises(OrderPreviewError):
            build_order_preview(payload, _rules())


def test_required_margin_and_fee_must_fit_available_balance() -> None:
    with pytest.raises(OrderPreviewError, match="available balance"):
        build_order_preview(_payload(available_balance="1"), _rules())


def test_maximum_risk_limit_and_hard_cap_are_enforced() -> None:
    with pytest.raises(OrderPreviewError, match="maximum risk"):
        build_order_preview(_payload(account_equity="100", max_risk_percent="1"), _rules())
    with pytest.raises(OrderPreviewError, match="hard preview limit"):
        build_order_preview(_payload(max_risk_percent="10"), _rules())


def test_spot_buy_checks_cash_and_spot_sell_checks_inventory() -> None:
    spot_rules = _rules("spot")
    buy = _payload(category="spot", leverage="1", available_balance="200", slippage_percent="0.1")
    assert build_order_preview(buy, spot_rules).required_capital > 100
    with pytest.raises(OrderPreviewError, match="available balance"):
        build_order_preview({**buy, "available_balance": "50"}, spot_rules)

    sell = _payload(
        category="spot",
        side="sell",
        leverage="1",
        stop_loss="110",
        take_profit="80",
        available_balance="0",
        available_asset_quantity="1",
    )
    assert build_order_preview(sell, spot_rules).required_capital == 0
    with pytest.raises(OrderPreviewError, match="asset quantity"):
        build_order_preview({**sell, "available_asset_quantity": "0.5"}, spot_rules)


def test_unsupported_inverse_and_mismatched_rules_fail_closed() -> None:
    inverse = _rules("linear")
    object.__setattr__(inverse, "category", "inverse")
    with pytest.raises(OrderPreviewError, match="supports spot and linear"):
        build_order_preview(_payload(category="inverse"), inverse)

    with pytest.raises(OrderPreviewError, match="do not match"):
        build_order_preview(_payload(symbol="ETHUSDT"), _rules())


def test_non_finite_inputs_and_limit_slippage_fail_closed() -> None:
    for value in ("nan", "inf", "-inf"):
        with pytest.raises(OrderPreviewError):
            build_order_preview(_payload(reference_price=value), _rules())
    with pytest.raises(OrderPreviewError, match="slippage_percent=0"):
        build_order_preview(_payload(order_type="limit", limit_price="100", slippage_percent="1"), _rules())
