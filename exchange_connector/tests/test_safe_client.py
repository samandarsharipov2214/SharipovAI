"""Tests for the safe exchange connector."""

from __future__ import annotations

import pytest

from exchange_connector import ExchangeConfig, SafeExchangeConnector


def test_disabled_exchange_status_blocks_everything(monkeypatch) -> None:
    """Default connector is disabled and cannot execute orders."""

    monkeypatch.delenv("EXCHANGE_MODE", raising=False)
    connector = SafeExchangeConnector()

    status = connector.status()

    assert status.mode == "disabled"
    assert status.can_read_market is False
    assert status.can_preview_orders is False
    assert status.can_execute_orders is False
    assert status.api_key_configured is False
    assert status.api_secret_configured is False


def test_sandbox_preview_counts_commission_as_loss() -> None:
    """Order preview must include commission as cost/loss."""

    connector = SafeExchangeConnector(
        ExchangeConfig(
            exchange_name="bybit",
            mode="sandbox",
            base_url="https://api-testnet.bybit.com",
            api_key_configured=True,
            api_secret_configured=True,
            live_trading_enabled=False,
            default_fee_rate=0.001,
        )
    )

    preview = connector.preview_order(symbol="BTCUSDT", side="BUY", quantity=0.1, price=60000)

    assert preview.notional == 6000.0
    assert preview.estimated_fee == 6.0
    assert preview.total_cost == 6006.0
    assert preview.break_even_price == 60060.0
    assert preview.commission_counted_as_loss is True
    assert preview.execution_allowed is False
    assert "blocked" in preview.warning.lower()


def test_sell_preview_subtracts_commission_from_proceeds() -> None:
    """SELL preview should subtract commission from received proceeds."""

    connector = SafeExchangeConnector(
        ExchangeConfig(
            exchange_name="bybit",
            mode="sandbox",
            base_url="https://api-testnet.bybit.com",
            api_key_configured=True,
            api_secret_configured=True,
            live_trading_enabled=False,
            default_fee_rate=0.002,
        )
    )

    preview = connector.preview_order(symbol="ETHUSDT", side="SELL", quantity=2, price=3000)

    assert preview.notional == 6000.0
    assert preview.estimated_fee == 12.0
    assert preview.total_cost == 5988.0
    assert preview.break_even_price == 2994.0
    assert preview.commission_counted_as_loss is True


def test_live_mode_still_requires_explicit_execution_flag() -> None:
    """API keys alone must not enable real execution."""

    connector = SafeExchangeConnector(
        ExchangeConfig(
            exchange_name="bybit",
            mode="live",
            base_url="https://api.bybit.com",
            api_key_configured=True,
            api_secret_configured=True,
            live_trading_enabled=False,
            default_fee_rate=0.001,
        )
    )

    status = connector.status()

    assert status.can_read_market is True
    assert status.can_preview_orders is True
    assert status.can_execute_orders is False


def test_place_order_is_blocked_even_when_live_gate_is_enabled() -> None:
    """Current implementation must never send a real order."""

    connector = SafeExchangeConnector(
        ExchangeConfig(
            exchange_name="bybit",
            mode="live",
            base_url="https://api.bybit.com",
            api_key_configured=True,
            api_secret_configured=True,
            live_trading_enabled=True,
            default_fee_rate=0.001,
        )
    )

    with pytest.raises(RuntimeError, match="Real exchange order execution is not implemented"):
        connector.place_order(symbol="BTCUSDT", side="BUY", quantity=0.1, price=60000)


def test_bad_order_inputs_raise_clear_errors() -> None:
    """Invalid order preview inputs should fail before any exchange call."""

    connector = SafeExchangeConnector(
        ExchangeConfig(
            exchange_name="bybit",
            mode="sandbox",
            base_url="https://api-testnet.bybit.com",
            api_key_configured=False,
            api_secret_configured=False,
            live_trading_enabled=False,
            default_fee_rate=0.001,
        )
    )

    with pytest.raises(ValueError, match="side must be BUY or SELL"):
        connector.preview_order(symbol="BTCUSDT", side="HOLD", quantity=1, price=100)
    with pytest.raises(ValueError, match="quantity must be greater than zero"):
        connector.preview_order(symbol="BTCUSDT", side="BUY", quantity=0, price=100)
    with pytest.raises(ValueError, match="price must be a positive number"):
        connector.preview_order(symbol="BTCUSDT", side="BUY", quantity=1, price="bad")
