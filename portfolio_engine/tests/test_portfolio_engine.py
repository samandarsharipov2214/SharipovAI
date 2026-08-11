"""Tests for the deterministic portfolio engine."""

from __future__ import annotations

import pytest

from portfolio_engine import (
    PortfolioEngine,
    PortfolioEngineError,
    PortfolioInput,
    Position,
)


def test_evaluate_empty_portfolio() -> None:
    output = PortfolioEngine().evaluate(PortfolioInput(cash=0.0, positions=[]))
    assert output.total_value == 0.0
    assert output.positions_value == 0.0
    assert output.exposure_percent == 0.0
    assert output.positions_count == 0
    assert output.largest_position_symbol is None
    assert any("Total value warning" in warning for warning in output.warnings)


def test_evaluate_cash_only() -> None:
    output = PortfolioEngine().evaluate(PortfolioInput(cash=1000.0, positions=[]))
    assert output.total_value == 1000.0
    assert output.cash == 1000.0
    assert output.positions_value == 0.0
    assert output.exposure_percent == 0.0
    assert output.positions_count == 0


def test_evaluate_one_position() -> None:
    output = PortfolioEngine().evaluate(
        PortfolioInput(cash=500.0, positions=[_position("BTC", 1.0, 1000.0)])
    )
    assert output.total_value == 1500.0
    assert output.positions_value == 1000.0
    assert output.exposure_percent == 66.67
    assert output.largest_position_symbol == "BTC"
    assert output.largest_position_percent == 66.67


def test_evaluate_multiple_positions() -> None:
    output = PortfolioEngine().evaluate(
        PortfolioInput(
            cash=100.0,
            positions=[
                _position("BTC", 1.0, 1000.0),
                _position("ETH", 2.0, 200.0),
            ],
        )
    )
    assert output.total_value == 1500.0
    assert output.positions_value == 1400.0
    assert output.positions_count == 2
    assert output.largest_position_symbol == "BTC"


def test_evaluate_exposure_warning() -> None:
    output = PortfolioEngine().evaluate(
        PortfolioInput(cash=100.0, positions=[_position("BTC", 9.0, 100.0)])
    )
    assert output.exposure_percent == 90.0
    assert any("Exposure warning" in warning for warning in output.warnings)


def test_evaluate_concentration_warning() -> None:
    output = PortfolioEngine().evaluate(
        PortfolioInput(cash=700.0, positions=[_position("BTC", 3.0, 100.0)])
    )
    assert output.largest_position_percent == 30.0
    assert any("Concentration warning" in warning for warning in output.warnings)


def test_evaluate_negative_quantity_invalid() -> None:
    with pytest.raises(PortfolioEngineError):
        PortfolioEngine().evaluate(
            PortfolioInput(cash=0.0, positions=[_position("BTC", -1.0, 100.0)])
        )


def test_evaluate_negative_price_invalid() -> None:
    with pytest.raises(PortfolioEngineError):
        PortfolioEngine().evaluate(
            PortfolioInput(
                cash=0.0,
                positions=[
                    Position(
                        symbol="BTC",
                        quantity=1.0,
                        average_price=100.0,
                        current_price=-1.0,
                    )
                ],
            )
        )


@pytest.mark.parametrize("cash", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_cash_is_rejected(cash: float) -> None:
    with pytest.raises(PortfolioEngineError, match="finite"):
        PortfolioEngine().evaluate(PortfolioInput(cash=cash, positions=[]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", float("nan")),
        ("average_price", float("inf")),
        ("current_price", float("-inf")),
    ],
)
def test_non_finite_position_values_are_rejected(field: str, value: float) -> None:
    position = Position(symbol="BTC", quantity=1.0, average_price=100.0, current_price=100.0)
    setattr(position, field, value)
    with pytest.raises(PortfolioEngineError, match="non-finite"):
        PortfolioEngine().evaluate(PortfolioInput(cash=100.0, positions=[position]))


def test_evaluate_zero_total_value() -> None:
    output = PortfolioEngine().evaluate(
        PortfolioInput(cash=0.0, positions=[_position("BTC", 1.0, 0.0)])
    )
    assert output.total_value == 0.0
    assert output.exposure_percent == 0.0
    assert output.largest_position_percent == 0.0
    assert any("Total value warning" in warning for warning in output.warnings)


def test_evaluate_largest_position_calculation() -> None:
    output = PortfolioEngine().evaluate(
        PortfolioInput(
            cash=100.0,
            positions=[
                _position("BTC", 1.0, 100.0),
                _position("ETH", 5.0, 50.0),
                _position("SOL", 2.0, 80.0),
            ],
        )
    )
    assert output.largest_position_symbol == "ETH"
    assert output.largest_position_percent == 40.98


def _position(symbol: str, quantity: float, current_price: float) -> Position:
    return Position(
        symbol=symbol,
        quantity=quantity,
        average_price=current_price,
        current_price=current_price,
    )
