"""Typed models for the SharipovAI runner."""

from __future__ import annotations

from dataclasses import dataclass

from learning_engine import LearningSummary


@dataclass(frozen=True, slots=True)
class RunnerOutput:
    """Output returned by the SharipovAI runner.

    Attributes:
        decision: Final decision label.
        confidence: Final decision confidence.
        risk_level: Evaluated risk level.
        portfolio_value: Evaluated portfolio value.
        paper_cash: Paper account cash.
        paper_equity: Paper account equity.
        learning_summary: Learning summary after recording the result.
        report: Human-readable runner report.
    """

    decision: str
    confidence: float
    risk_level: str
    portfolio_value: float
    paper_cash: float
    paper_equity: float
    learning_summary: LearningSummary
    report: str
    reason: str = ""
    consensus: str = ""
    consensus_agreement: float = 0.0
    paper_pnl: float = 0.0
    open_positions: int = 0
