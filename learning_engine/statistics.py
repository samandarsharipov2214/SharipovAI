"""Deterministic statistics for learning records."""

from __future__ import annotations

from .models import LearningRecord, LearningSummary


class LearningStatistics:
    """Calculates deterministic learning statistics."""

    def summarize(self, records: list[LearningRecord]) -> LearningSummary:
        """Summarize learning records.

        Args:
            records: Learning records to summarize.

        Returns:
            Learning summary.
        """

        profits = [record.profit_loss for record in records if record.profit_loss > 0]
        losses = [record.profit_loss for record in records if record.profit_loss < 0]
        wins = len([record for record in records if record.success])
        failed = len(records) - wins
        win_rate = self.win_rate(wins=wins, total=len(records))
        average_profit = self.average_profit(profits)
        average_loss = self.average_loss(losses)
        summary = LearningSummary(
            total_trades=len(records),
            wins=wins,
            losses=failed,
            win_rate=win_rate,
            average_profit=average_profit,
            average_loss=average_loss,
            best_trade=self.best_trade(records),
            worst_trade=self.worst_trade(records),
            recommendations=[],
        )

        return LearningSummary(
            total_trades=summary.total_trades,
            wins=summary.wins,
            losses=summary.losses,
            win_rate=summary.win_rate,
            average_profit=summary.average_profit,
            average_loss=summary.average_loss,
            best_trade=summary.best_trade,
            worst_trade=summary.worst_trade,
            recommendations=self.recommendations(summary),
        )

    def win_rate(self, *, wins: int, total: int) -> float:
        """Calculate win rate percentage.

        Args:
            wins: Number of wins.
            total: Total number of trades.

        Returns:
            Win rate percentage.
        """

        if total == 0:
            return 0.0
        return round((wins / total) * 100.0, 2)

    def average_profit(self, profits: list[float]) -> float:
        """Calculate average profit.

        Args:
            profits: Positive profit values.

        Returns:
            Average profit.
        """

        if not profits:
            return 0.0
        return round(sum(profits) / len(profits), 2)

    def average_loss(self, losses: list[float]) -> float:
        """Calculate average loss.

        Args:
            losses: Negative loss values.

        Returns:
            Average loss as a positive magnitude.
        """

        if not losses:
            return 0.0
        return round(abs(sum(losses) / len(losses)), 2)

    def best_trade(self, records: list[LearningRecord]) -> float:
        """Return best trade profit or loss.

        Args:
            records: Learning records.

        Returns:
            Best profit or loss value.
        """

        if not records:
            return 0.0
        return max(record.profit_loss for record in records)

    def worst_trade(self, records: list[LearningRecord]) -> float:
        """Return worst trade profit or loss.

        Args:
            records: Learning records.

        Returns:
            Worst profit or loss value.
        """

        if not records:
            return 0.0
        return min(record.profit_loss for record in records)

    def recommendations(self, summary: LearningSummary) -> list[str]:
        """Generate deterministic learning recommendations.

        Args:
            summary: Learning summary.

        Returns:
            Recommendation messages.
        """

        recommendations: list[str] = []

        if summary.win_rate < 40:
            recommendations.append("Strategy quality is poor.")

        if summary.average_loss > summary.average_profit:
            recommendations.append("Losses exceed profits.")

        if summary.win_rate > 70:
            recommendations.append("Current strategy performs well.")

        if summary.total_trades < 10:
            recommendations.append("More historical data is required.")

        return recommendations
