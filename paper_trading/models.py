"""Typed models for virtual paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(slots=True)
class PaperAccount:
    """Virtual paper trading account.

    Attributes:
        cash: Available virtual cash.
        equity: Current account equity.
        realized_pnl: Realized profit and loss.
        unrealized_pnl: Unrealized profit and loss.
    """

    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float


@dataclass(slots=True)
class PaperPosition:
    """Virtual paper trading position.

    Attributes:
        symbol: Position symbol.
        quantity: Open position quantity.
        entry_price: Average entry price.
        current_price: Latest market price.
    """

    symbol: str
    quantity: float
    entry_price: float
    current_price: float


@dataclass(slots=True)
class PaperTrade:
    """Virtual paper trade record.

    Attributes:
        symbol: Trade symbol.
        side: Trade side.
        quantity: Trade quantity.
        price: Trade execution price.
        timestamp: Trade timestamp.
    """

    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: float
    timestamp: datetime
