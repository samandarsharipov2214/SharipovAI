"""Performance statistics for virtual paper trading."""

from __future__ import annotations

from dataclasses import dataclass

from .models import PaperAccount, PaperTrade


@dataclass(frozen=True, slots=True)
class PerformanceStats:
    """Paper trading performance statistics.

    Attributes:
        total_return_percent: Total return percentage.
        win_rate: Percentage of profitable closed trades.
        average_profit: Average profit across winning closed trades.
        average_loss: Average loss across losing closed trades.
        number_of_trades: Number of stored trades.
        current_equity: Current account equity.
        max_drawdown: Maximum drawdown percentage from the equity curve.
    """

    total_return_percent: float
    win_rate: float
    average_profit: float
    average_loss: float
    number_of_trades: int
    current_equity: float
    max_drawdown: float


class PerformanceCalculator:
    """Calculates deterministic paper trading performance statistics."""

    def calculate(
        self,
        *,
        initial_balance: float,
        account: PaperAccount,
        trades: list[PaperTrade],
        closed_trade_pnls: list[float],
        equity_curve: list[float],
    ) -> PerformanceStats:
        """Calculate performance statistics.

        Args:
            initial_balance: Initial virtual account balance.
            account: Current paper account.
            trades: Stored paper trades.
            closed_trade_pnls: Realized PnL values for sell operations.
            equity_curve: Historical equity values.

        Returns:
            Calculated performance statistics.
        """

        wins = [pnl for pnl in closed_trade_pnls if pnl > 0]
        losses = [pnl for pnl in closed_trade_pnls if pnl < 0]
        closed_count = len(closed_trade_pnls)
        total_return_percent = _percent(account.equity - initial_balance, initial_balance)
        win_rate = _percent(len(wins), closed_count)

        return PerformanceStats(
            total_return_percent=round(total_return_percent, 2),
            win_rate=round(win_rate, 2),
            average_profit=round(sum(wins) / len(wins), 2) if wins else 0.0,
            average_loss=round(sum(losses) / len(losses), 2) if losses else 0.0,
            number_of_trades=len(trades),
            current_equity=round(account.equity, 2),
            max_drawdown=round(_max_drawdown(equity_curve), 2),
        )


def _percent(numerator: float, denominator: float) -> float:
    """Calculate a percentage safely."""

    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _max_drawdown(equity_curve: list[float]) -> float:
    """Calculate simple maximum drawdown from an equity curve."""

    peak = 0.0
    max_drawdown = 0.0

    for equity in equity_curve:
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown = ((peak - equity) / peak) * 100.0
        max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown
