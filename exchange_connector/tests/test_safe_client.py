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
    assert preview.entry_fee == 6.0
    assert preview.expected_exit_fee == 0.0
    assert preview.total_fees == 6.0
    assert preview.total_cost == 6006.0
    assert preview.break_even_price == 60120.0
    assert preview.commission_counted_as_loss is True
    assert preview.execution_allowed is False
    assert "blocked" in preview.warning.lower()


def test_preview_calculates_net_result_after_fees() -> None:
    """AI must see profit after entry and exit commissions, not only gross profit."""

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

    preview = connector.preview_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=1,
        price=100.0,
        expected_exit_price=101.0,
    )

    assert preview.entry_fee == pytest.approx(0.1)
    assert preview.expected_exit_fee == pytest.approx(0.101)
    assert preview.total_fees == pytest.approx(0.201)
    assert preview.gross_result == pytest.approx(1.0)
    assert preview.net_result_after_fees == pytest.approx(0.799)
    assert preview.commission_drag == pytest.approx(0.201)


def test_preview_warns_when_commission_erases_profit() -> None:
    """Tiny gross profits should be rejected when commissions make them net losses."""

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

    preview = connector.preview_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=1,
        price=100.0,
        expected_exit_price=100.05,
    )

    assert preview.gross_result == pytest.approx(0.05)
    assert preview.net_result_after_fees is not None
    assert preview.net_result_after_fees < 0
    assert "Do not trade" in preview.warning


def test_sell_preview_subtracts_commission_from_expected_short_result() -> None:
    """SELL preview should also subtract commissions from expected result."""

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

    preview = connector.preview_order(
        symbol="ETHUSDT",
        side="SELL",
        quantity=2,
        price=3000,
        expected_exit_price=2900,
    )

    assert preview.notional == 6000.0
    assert preview.entry_fee == 12.0
    assert preview.expected_exit_fee == 11.6
    assert preview.total_fees == 23.6
    assert preview.gross_result == 200.0
    assert preview.net_result_after_fees == pytest.approx(176.4)
    assert preview.break_even_price == 2988.0
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
