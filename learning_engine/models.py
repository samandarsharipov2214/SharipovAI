"""Typed models for the learning engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from decision.models import DecisionOutput
from paper_trading.models import PaperTrade


@dataclass(frozen=True, slots=True)
class LearningRecord:
    """Stored learning record.

    Attributes:
        trade: Paper trade associated with the decision outcome.
        decision: Decision output that produced the analytical decision.
        profit_loss: Realized profit or loss.
        success: Whether the outcome was successful.
    """

    trade: PaperTrade
    decision: DecisionOutput
    profit_loss: float
    success: bool


@dataclass(frozen=True, slots=True)
class LearningSummary:
    """Summary of learning records.

    Attributes:
        total_trades: Number of recorded trades.
        wins: Number of successful trades.
        losses: Number of unsuccessful trades.
        win_rate: Win rate percentage.
        average_profit: Average profit from winning trades.
        average_loss: Average loss from losing trades.
        best_trade: Best recorded profit or loss.
        worst_trade: Worst recorded profit or loss.
        recommendations: Deterministic recommendations.
    """

    total_trades: int
    wins: int
    losses: int
    win_rate: float
    average_profit: float
    average_loss: float
    best_trade: float
    worst_trade: float
    recommendations: list[str] = field(default_factory=list)
