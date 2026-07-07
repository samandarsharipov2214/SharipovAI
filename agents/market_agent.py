"""Market Agent implementation.

The Market Agent performs deterministic market analysis over provided ticker
models. It does not include API calls, API keys, order logic, trading
execution, or exchange communication.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from analysis import FactorEngine, MarketAnalyzer, MarketScorer, SignalEngine
from bybit import TickerInfo
from core.orchestrator import Agent, AgentResult

from .models import MarketAgentData


class MarketAgent(Agent):
    """Deterministic market analysis agent."""

    AGENT_NAME: str = "Market Agent"
    TOP_LIMIT: int = 20

    def __init__(
        self,
        analyzer: MarketAnalyzer | None = None,
        scorer: MarketScorer | None = None,
        signal_engine: SignalEngine | None = None,
    ) -> None:
        """Initialize the Market Agent.

        Args:
            analyzer: Optional market analyzer dependency.
            scorer: Optional market scorer dependency.
            signal_engine: Optional signal engine dependency.
        """

        self._analyzer = analyzer or MarketAnalyzer()
        self._scorer = scorer or MarketScorer()
        self._signal_engine = signal_engine or SignalEngine()

    def name(self) -> str:
        """Return the agent name.

        Returns:
            Agent name used by the orchestrator.
        """

        return self.AGENT_NAME

    def run(self, context: Mapping[str, Any]) -> AgentResult:
        """Run deterministic market analysis.

        Args:
            context: Execution context containing ``tickers``.

        Returns:
            Agent result containing market analysis output.
        """

        tickers = self._extract_tickers(context)
        if not tickers:
            return AgentResult(
                agent_name=self.AGENT_NAME,
                success=False,
                confidence=0.0,
                summary="Market Agent failed because no tickers were provided.",
                data={"error": "missing_tickers"},
            )

        ranked_tickers = self._scorer.rank(tickers)
        top_tickers = ranked_tickers[: self.TOP_LIMIT]
        top_ticker = top_tickers[0]
        top_score = self._scorer.score(top_ticker)
        top_signal = self._signal_engine.generate_signal(top_ticker, top_score)
        factor_engine = FactorEngine.from_tickers(tickers)
        factor_scores = factor_engine.evaluate(top_ticker)

        data = MarketAgentData(
            top_symbol=top_ticker.symbol,
            top_score=top_score,
            top_signal=top_signal.signal,
            top_reason=top_signal.reason,
            top_20_symbols=[ticker.symbol for ticker in top_tickers],
            factor_scores=factor_scores,
        )

        top_volume_symbols = [
            ticker.symbol
            for ticker in self._analyzer.analyze_top_volume(tickers)[: self.TOP_LIMIT]
        ]
        result_data = data.to_dict()
        result_data["top_volume_symbols"] = top_volume_symbols

        return AgentResult(
            agent_name=self.AGENT_NAME,
            success=True,
            confidence=top_score,
            summary=(
                f"Market Agent analyzed {len(tickers)} tickers. "
                f"Top symbol is {top_ticker.symbol} with score {top_score:.2f}."
            ),
            data=result_data,
        )

    def _extract_tickers(self, context: Mapping[str, Any]) -> list[TickerInfo]:
        """Extract typed tickers from execution context.

        Args:
            context: Execution context.

        Returns:
            List of typed ticker models. Invalid items are ignored.
        """

        raw_tickers = context.get("tickers")
        if raw_tickers is None or isinstance(raw_tickers, (str, bytes)):
            return []

        if not isinstance(raw_tickers, Sequence):
            return []

        return [ticker for ticker in raw_tickers if isinstance(ticker, TickerInfo)]
