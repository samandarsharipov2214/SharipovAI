"""Executable offline SharipovAI pipeline runner.

The runner connects existing deterministic components into a single pipeline.
It uses static sample data only and performs no real API calls, exchange
execution, or AI model calls.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agents import MarketAgent
from ai_core import AICore, AICoreInput
from bybit import TickerInfo
from core.orchestrator import Orchestrator
from data_layer import DataItem
from data_layer.providers import RSSProvider
from decision import DecisionType
from learning_engine import LearningEngine, LearningRecord
from memory import MemoryEngine
from news_agent import NewsAgent
from paper_trading import PaperEngine, PaperTrade
from portfolio_engine import PortfolioInput, Position
from risk_engine import RiskInput

from .models import RunnerOutput


class SharipovAIRunner:
    """Runs the offline SharipovAI analytical pipeline."""

    def __init__(
        self,
        memory_engine: MemoryEngine | None = None,
        paper_engine: PaperEngine | None = None,
        learning_engine: LearningEngine | None = None,
    ) -> None:
        """Initialize the runner.

        Args:
            memory_engine: Optional memory engine dependency.
            paper_engine: Optional paper engine dependency.
            learning_engine: Optional learning engine dependency.
        """

        self._memory_engine = memory_engine or MemoryEngine()
        self._paper_engine = paper_engine or PaperEngine()
        self._learning_engine = learning_engine or LearningEngine(
            memory_engine=self._memory_engine
        )
        self._last_orchestrator: Orchestrator | None = None

    @property
    def last_orchestrator(self) -> Orchestrator | None:
        """Return the last orchestrator used by the runner."""

        return self._last_orchestrator

    def run(self) -> RunnerOutput:
        """Run the complete offline SharipovAI pipeline.

        Returns:
            Runner output.
        """

        tickers = self._sample_tickers()
        news_items = self._sample_news_items()
        orchestrator = Orchestrator()
        orchestrator.register_agent(MarketAgent())
        orchestrator.register_agent(NewsAgent(RSSProvider(items=news_items)))
        self._last_orchestrator = orchestrator

        ai_core = AICore(
            orchestrator=orchestrator,
            memory_engine=self._memory_engine,
        )
        portfolio_input = self._portfolio_input()
        risk_input = self._risk_input()
        ai_output = ai_core.run(
            AICoreInput(
                context={
                    "symbol": "BTCUSDT",
                    "tickers": tickers,
                    "data_quality": 100.0,
                },
                portfolio=portfolio_input,
                risk=risk_input,
            )
        )

        self._paper_engine.create_account(10000.0)
        trade = None
        if ai_output.decision.decision is DecisionType.BUY:
            trade = self._paper_engine.buy(
                symbol="BTCUSDT",
                quantity=0.01,
                price=50000.0,
            )

        if trade is None:
            trade = PaperTrade(
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.0,
                price=50000.0,
                timestamp=datetime.now(timezone.utc),
            )

        paper_account = self._paper_engine.account()
        self._learning_engine.record(
            LearningRecord(
                trade=trade,
                decision=ai_output.decision,
                profit_loss=0.0,
                success=ai_output.decision.decision is DecisionType.BUY,
            )
        )
        learning_summary = self._learning_engine.summary()

        return RunnerOutput(
            decision=ai_output.decision.decision.value,
            confidence=ai_output.decision.confidence,
            risk_level=ai_output.risk.risk_level.value,
            portfolio_value=ai_output.portfolio.total_value,
            paper_cash=paper_account.cash,
            paper_equity=paper_account.equity,
            learning_summary=learning_summary,
            report=self._report(ai_output, paper_account, learning_summary),
        )

    def _sample_tickers(self) -> list[TickerInfo]:
        """Create static sample market tickers."""

        return [
            TickerInfo(
                category="spot",
                symbol="BTCUSDT",
                last_price="50000",
                bid_price="49990",
                ask_price="50010",
                price_24h_change_percent="0.03",
                volume_24h="2000",
                turnover_24h="10000000",
            ),
            TickerInfo(
                category="spot",
                symbol="ETHUSDT",
                last_price="2500",
                bid_price="2499",
                ask_price="2501",
                price_24h_change_percent="0.01",
                volume_24h="1000",
                turnover_24h="2500000",
            ),
            TickerInfo(
                category="spot",
                symbol="SOLUSDT",
                last_price="150",
                bid_price="149",
                ask_price="151",
                price_24h_change_percent="-0.02",
                volume_24h="500",
                turnover_24h="750000",
            ),
        ]

    def _sample_news_items(self) -> list[DataItem]:
        """Create static sample news items."""

        return [
            DataItem(
                source="static-rss",
                category="news",
                title="Bitcoin ETF Approval",
                content="Bitcoin ETF approval supports bullish market sentiment.",
                url=None,
                published_at=datetime.now(timezone.utc),
                metadata={},
            ),
            DataItem(
                source="static-rss",
                category="news",
                title="Fed rate update",
                content="Fed discusses inflation and rate policy.",
                url=None,
                published_at=datetime.now(timezone.utc),
                metadata={},
            ),
        ]

    def _portfolio_input(self) -> PortfolioInput:
        """Create static sample portfolio input."""

        return PortfolioInput(
            cash=10000.0,
            positions=[
                Position(
                    symbol="BTCUSDT",
                    quantity=0.01,
                    average_price=48000.0,
                    current_price=50000.0,
                )
            ],
        )

    def _risk_input(self) -> RiskInput:
        """Create static sample risk input."""

        return RiskInput(
            portfolio_drawdown=1.0,
            portfolio_exposure=10.0,
            asset_exposure=5.0,
            volatility_score=10.0,
            liquidity_score=90.0,
            correlation_score=10.0,
        )

    def _report(self, ai_output: object, paper_account: object, learning_summary: object) -> str:
        """Generate a human-readable runner report."""

        return (
            "SharipovAI runner completed. "
            f"Decision: {ai_output.decision.decision.value}. "
            f"Confidence: {ai_output.decision.confidence:.2f}. "
            f"Risk: {ai_output.risk.risk_level.value}. "
            f"Paper equity: {paper_account.equity:.2f}. "
            f"Learning trades: {learning_summary.total_trades}."
        )
