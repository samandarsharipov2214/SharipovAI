"""Tests for the virtual paper trading engine."""

from __future__ import annotations

import pytest

from paper_trading import PaperEngine, PaperTradingError


def test_create_account() -> None:
    """Account creation initializes cash and equity."""

    account = PaperEngine().create_account(1000.0)

    assert account.cash == 1000.0
    assert account.equity == 1000.0
    assert account.realized_pnl == 0.0
    assert account.unrealized_pnl == 0.0


def test_buy() -> None:
    """Buying creates a position and reduces cash."""

    engine = _engine()
    trade = engine.buy("BTCUSDT", 1.0, 100.0)

    assert trade.side == "BUY"
    assert engine.account().cash == 900.0
    assert engine.positions()[0].quantity == 1.0
    assert len(engine.history()) == 1


def test_sell() -> None:
    """Selling reduces a position and increases cash."""

    engine = _engine()
    engine.buy("BTCUSDT", 2.0, 100.0)
    trade = engine.sell("BTCUSDT", 1.0, 120.0)

    assert trade.side == "SELL"
    assert engine.account().cash == 920.0
    assert engine.positions()[0].quantity == 1.0


def test_partial_sell() -> None:
    """Partial sell keeps the remaining position open."""

    engine = _engine()
    engine.buy("BTCUSDT", 3.0, 100.0)
    engine.sell("BTCUSDT", 1.0, 110.0)

    position = engine.positions()[0]
    assert position.quantity == 2.0
    assert position.entry_price == 100.0


def test_close_position() -> None:
    """Closing a position sells all remaining quantity."""

    engine = _engine()
    engine.buy("BTCUSDT", 1.0, 100.0)
    engine.update_market_price("BTCUSDT", 130.0)
    trade = engine.close_position("BTCUSDT")

    assert trade.side == "SELL"
    assert engine.positions() == []
    assert engine.account().realized_pnl == 30.0


def test_profit_calculation() -> None:
    """Profitable sells update realized PnL."""

    engine = _engine()
    engine.buy("BTCUSDT", 1.0, 100.0)
    engine.sell("BTCUSDT", 1.0, 150.0)

    assert engine.account().realized_pnl == 50.0


def test_loss_calculation() -> None:
    """Losing sells update realized PnL."""

    engine = _engine()
    engine.buy("BTCUSDT", 1.0, 100.0)
    engine.sell("BTCUSDT", 1.0, 80.0)

    assert engine.account().realized_pnl == -20.0


def test_equity_update() -> None:
    """Market price updates refresh equity and unrealized PnL."""

    engine = _engine()
    engine.buy("BTCUSDT", 1.0, 100.0)
    engine.update_market_price("BTCUSDT", 150.0)

    account = engine.account()
    assert account.equity == 1050.0
    assert account.unrealized_pnl == 50.0


def test_insufficient_cash() -> None:
    """Buying more than cash allows is rejected."""

    engine = _engine()

    with pytest.raises(PaperTradingError):
        engine.buy("BTCUSDT", 20.0, 100.0)


def test_oversell_prevention() -> None:
    """Selling more than owned is rejected."""

    engine = _engine()
    engine.buy("BTCUSDT", 1.0, 100.0)

    with pytest.raises(PaperTradingError):
        engine.sell("BTCUSDT", 2.0, 100.0)


def test_performance_statistics() -> None:
    """Performance statistics summarize paper trading history."""

    engine = _engine()
    engine.buy("BTCUSDT", 1.0, 100.0)
    engine.update_market_price("BTCUSDT", 150.0)
    engine.sell("BTCUSDT", 1.0, 150.0)
    engine.buy("ETHUSDT", 1.0, 100.0)
    engine.sell("ETHUSDT", 1.0, 80.0)
    stats = engine.performance()

    assert stats.number_of_trades == 4
    assert stats.current_equity == 1030.0
    assert stats.total_return_percent == 3.0
    assert stats.win_rate == 50.0
    assert stats.average_profit == 50.0
    assert stats.average_loss == -20.0
    assert stats.max_drawdown > 0


def _engine() -> PaperEngine:
    """Create an initialized paper engine."""

    engine = PaperEngine()
    engine.create_account(1000.0)
    return engine
