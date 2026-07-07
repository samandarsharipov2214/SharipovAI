"""Virtual paper trading engine.

The engine simulates trades with virtual money only. It does not perform
exchange execution, API calls, API key handling, or AI model calls.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .exceptions import PaperTradingError
from .models import PaperAccount, PaperPosition, PaperTrade
from .performance import PerformanceCalculator, PerformanceStats


class PaperEngine:
    """Simulates virtual trading with paper account state."""

    def __init__(self) -> None:
        """Initialize an empty paper trading engine."""

        self._initial_balance: float | None = None
        self._account: PaperAccount | None = None
        self._positions: dict[str, PaperPosition] = {}
        self._history: list[PaperTrade] = []
        self._closed_trade_pnls: list[float] = []
        self._equity_curve: list[float] = []
        self._performance_calculator = PerformanceCalculator()

    def create_account(self, initial_balance: float) -> PaperAccount:
        """Create a virtual paper trading account.

        Args:
            initial_balance: Initial virtual cash balance.

        Returns:
            Created paper account.

        Raises:
            PaperTradingError: If initial balance is negative.
        """

        if initial_balance < 0:
            raise PaperTradingError("Initial balance must not be negative.")

        self._initial_balance = initial_balance
        self._account = PaperAccount(
            cash=initial_balance,
            equity=initial_balance,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        self._positions = {}
        self._history = []
        self._closed_trade_pnls = []
        self._equity_curve = [initial_balance]
        return self.account()

    def buy(self, symbol: str, quantity: float, price: float) -> PaperTrade:
        """Simulate a virtual buy.

        Args:
            symbol: Trade symbol.
            quantity: Quantity to buy.
            price: Virtual execution price.

        Returns:
            Stored paper trade.

        Raises:
            PaperTradingError: If account state or trade values are invalid.
        """

        self._ensure_account()
        self._validate_trade_values(symbol, quantity, price)
        cost = quantity * price
        account = self._account
        if account is None:
            raise PaperTradingError("Paper account is not initialized.")

        if cost > account.cash:
            raise PaperTradingError("Insufficient cash for paper buy.")

        existing = self._positions.get(symbol)
        if existing is None:
            self._positions[symbol] = PaperPosition(
                symbol=symbol,
                quantity=quantity,
                entry_price=price,
                current_price=price,
            )
        else:
            new_quantity = existing.quantity + quantity
            weighted_entry = (
                (existing.quantity * existing.entry_price) + cost
            ) / new_quantity
            self._positions[symbol] = PaperPosition(
                symbol=symbol,
                quantity=new_quantity,
                entry_price=weighted_entry,
                current_price=price,
            )

        account.cash -= cost
        trade = self._record_trade(symbol=symbol, side="BUY", quantity=quantity, price=price)
        self._recalculate_account()
        return trade

    def sell(self, symbol: str, quantity: float, price: float) -> PaperTrade:
        """Simulate a virtual sell.

        Args:
            symbol: Trade symbol.
            quantity: Quantity to sell.
            price: Virtual execution price.

        Returns:
            Stored paper trade.

        Raises:
            PaperTradingError: If selling more than owned or values are invalid.
        """

        self._ensure_account()
        self._validate_trade_values(symbol, quantity, price)
        position = self._positions.get(symbol)
        if position is None or quantity > position.quantity:
            raise PaperTradingError("Cannot sell more than owned.")

        account = self._account
        if account is None:
            raise PaperTradingError("Paper account is not initialized.")

        proceeds = quantity * price
        realized_pnl = (price - position.entry_price) * quantity
        account.cash += proceeds
        account.realized_pnl += realized_pnl
        self._closed_trade_pnls.append(realized_pnl)

        remaining_quantity = position.quantity - quantity
        if remaining_quantity == 0:
            del self._positions[symbol]
        else:
            self._positions[symbol] = PaperPosition(
                symbol=symbol,
                quantity=remaining_quantity,
                entry_price=position.entry_price,
                current_price=price,
            )

        trade = self._record_trade(symbol=symbol, side="SELL", quantity=quantity, price=price)
        self._recalculate_account()
        return trade

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update the virtual market price for a position.

        Args:
            symbol: Position symbol.
            price: Updated market price.

        Raises:
            PaperTradingError: If the price is invalid or position is missing.
        """

        self._ensure_account()
        if price < 0:
            raise PaperTradingError("Market price must not be negative.")

        position = self._positions.get(symbol)
        if position is None:
            raise PaperTradingError(f"Position '{symbol}' does not exist.")

        self._positions[symbol] = PaperPosition(
            symbol=position.symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            current_price=price,
        )
        self._recalculate_account()

    def close_position(self, symbol: str) -> PaperTrade:
        """Close an open virtual position at its current price.

        Args:
            symbol: Position symbol.

        Returns:
            Stored closing sell trade.

        Raises:
            PaperTradingError: If the position is missing.
        """

        position = self._positions.get(symbol)
        if position is None:
            raise PaperTradingError(f"Position '{symbol}' does not exist.")

        return self.sell(symbol, position.quantity, position.current_price)

    def account(self) -> PaperAccount:
        """Return a copy of the current account.

        Returns:
            Current paper account.

        Raises:
            PaperTradingError: If account has not been created.
        """

        self._ensure_account()
        if self._account is None:
            raise PaperTradingError("Paper account is not initialized.")
        return replace(self._account)

    def positions(self) -> list[PaperPosition]:
        """Return copies of open positions."""

        return [replace(position) for position in self._positions.values()]

    def history(self) -> list[PaperTrade]:
        """Return copies of stored trades."""

        return [replace(trade) for trade in self._history]

    def performance(self) -> PerformanceStats:
        """Calculate current paper trading performance statistics.

        Returns:
            Performance statistics.

        Raises:
            PaperTradingError: If account has not been created.
        """

        self._ensure_account()
        if self._initial_balance is None or self._account is None:
            raise PaperTradingError("Paper account is not initialized.")

        return self._performance_calculator.calculate(
            initial_balance=self._initial_balance,
            account=self._account,
            trades=self._history,
            closed_trade_pnls=self._closed_trade_pnls,
            equity_curve=self._equity_curve,
        )

    def _ensure_account(self) -> None:
        """Ensure the account exists."""

        if self._account is None:
            raise PaperTradingError("Create a paper account before trading.")

    def _validate_trade_values(self, symbol: str, quantity: float, price: float) -> None:
        """Validate trade values."""

        if not symbol.strip():
            raise PaperTradingError("Symbol must not be empty.")

        if quantity <= 0:
            raise PaperTradingError("Quantity must be greater than zero.")

        if price < 0:
            raise PaperTradingError("Price must not be negative.")

    def _record_trade(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ) -> PaperTrade:
        """Record a virtual paper trade."""

        trade = PaperTrade(
            symbol=symbol,
            side="BUY" if side == "BUY" else "SELL",
            quantity=quantity,
            price=price,
            timestamp=datetime.now(timezone.utc),
        )
        self._history.append(trade)
        return replace(trade)

    def _recalculate_account(self) -> None:
        """Recalculate account equity and unrealized PnL."""

        account = self._account
        if account is None:
            raise PaperTradingError("Paper account is not initialized.")

        positions_value = sum(
            position.quantity * position.current_price
            for position in self._positions.values()
        )
        account.unrealized_pnl = sum(
            (position.current_price - position.entry_price) * position.quantity
            for position in self._positions.values()
        )
        account.equity = account.cash + positions_value

        if account.cash < 0:
            raise PaperTradingError("Negative cash is not allowed.")

        self._equity_curve.append(account.equity)
