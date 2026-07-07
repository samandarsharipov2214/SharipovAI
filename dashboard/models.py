"""Typed dashboard view models."""

from __future__ import annotations

from dataclasses import dataclass

from learning_engine import LearningSummary


@dataclass(frozen=True, slots=True)
class DashboardView:
    """View model rendered by the dashboard.

    Attributes:
        run_mode: Active runner mode.
        decision: Final decision label.
        confidence: Final confidence score.
        risk_level: Risk level label.
        portfolio_value: Portfolio value.
        paper_cash: Paper account cash.
        paper_equity: Paper account equity.
        learning_summary: Learning summary.
        report: Text report.
        reason: Decision reason.
        consensus: Consensus level.
        consensus_agreement: Consensus agreement score.
        paper_pnl: Paper account profit and loss.
        open_positions: Number of open paper positions.
    """

    run_mode: str
    decision: str
    confidence: float
    risk_level: str
    portfolio_value: float
    paper_cash: float
    paper_equity: float
    learning_summary: LearningSummary
    report: str
    reason: str
    consensus: str
    consensus_agreement: float
    paper_pnl: float
    open_positions: int

    def to_dict(self) -> dict[str, object]:
        """Convert the view model to a JSON-compatible dictionary.

        Returns:
            Dictionary representation.
        """

        return {
            "run_mode": self.run_mode,
            "decision": self.decision,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "portfolio_value": self.portfolio_value,
            "paper_cash": self.paper_cash,
            "paper_equity": self.paper_equity,
            "learning_summary": {
                "total_trades": self.learning_summary.total_trades,
                "wins": self.learning_summary.wins,
                "losses": self.learning_summary.losses,
                "win_rate": self.learning_summary.win_rate,
                "average_profit": self.learning_summary.average_profit,
                "average_loss": self.learning_summary.average_loss,
                "best_trade": self.learning_summary.best_trade,
                "worst_trade": self.learning_summary.worst_trade,
                "recommendations": list(self.learning_summary.recommendations),
            },
            "report": self.report,
            "reason": self.reason,
            "consensus": self.consensus,
            "consensus_agreement": self.consensus_agreement,
            "paper_pnl": self.paper_pnl,
            "open_positions": self.open_positions,
        }


@dataclass(frozen=True, slots=True)
class CrashTestResult:
    """Deterministic crash-test result displayed by the web UI.

    Attributes:
        scenario: Scenario identifier.
        capital_before: Capital before the simulated event.
        capital_after: Capital after the simulated event.
        loss_amount: Simulated loss amount.
        loss_percent: Simulated loss percent.
        ai_reaction: AI reaction summary.
        protective_measures: Protective measures selected by the system.
        result: Human-readable result.
    """

    scenario: str
    capital_before: float
    capital_after: float
    loss_amount: float
    loss_percent: float
    ai_reaction: str
    protective_measures: list[str]
    result: str

    def to_dict(self) -> dict[str, object]:
        """Convert the crash-test result to a JSON-compatible dictionary.

        Returns:
            Dictionary representation.
        """

        return {
            "scenario": self.scenario,
            "capital_before": self.capital_before,
            "capital_after": self.capital_after,
            "loss_amount": self.loss_amount,
            "loss_percent": self.loss_percent,
            "ai_reaction": self.ai_reaction,
            "protective_measures": list(self.protective_measures),
            "result": self.result,
        }
