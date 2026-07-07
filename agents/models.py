"""Typed models for agent outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analysis import FactorScore


@dataclass(frozen=True, slots=True)
class MarketAgentData:
    """Structured data produced by the Market Agent.

    Attributes:
        top_symbol: Highest-ranked ticker symbol.
        top_score: Highest-ranked ticker score.
        top_signal: Signal generated for the highest-ranked ticker.
        top_reason: Reason associated with the generated signal.
        top_20_symbols: Symbols of the top 20 ranked tickers.
        factor_scores: Factor scores evaluated for the top ticker.
    """

    top_symbol: str
    top_score: float
    top_signal: str
    top_reason: str
    top_20_symbols: list[str]
    factor_scores: list[FactorScore]

    def to_dict(self) -> dict[str, Any]:
        """Convert the model to an ``AgentResult.data`` dictionary.

        Returns:
            Dictionary representation suitable for ``AgentResult.data``.
        """

        return {
            "top_symbol": self.top_symbol,
            "top_score": self.top_score,
            "top_signal": self.top_signal,
            "top_reason": self.top_reason,
            "top_20_symbols": list(self.top_20_symbols),
            "factor_scores": [
                {
                    "name": factor.name,
                    "score": factor.score,
                    "weight": factor.weight,
                    "reason": factor.reason,
                }
                for factor in self.factor_scores
            ],
        }
