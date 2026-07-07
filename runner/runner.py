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
import config.settings as config_settings
from core.orchestrator import Orchestrator
from data_layer import DataItem
from data_layer.models import DataBatch
from data_layer.providers import (
    BaseDataProvider,
    LiveMarketProvider,
    LiveRSSProvider,
    MarketDataProvider,
    RSSProvider,
)
from decision import DecisionType
from learning_engine import LearningEngine, LearningRecord
from memory import MemoryEngine
from news_agent import NewsAgent
from paper_trading import PaperEngine, PaperTrade
from portfolio_engine import PortfolioInput, Position
from risk_engine import RiskInput

from .exceptions import RunnerError
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
        self._last_market_provider_name: str | None = None
        self._last_news_provider_name: str | None = None

    @property
    def last_orchestrator(self) -> Orchestrator | None:
        """Return the last orchestrator used by the runner."""

        return self._last_orchestrator

    @property
    def last_market_provider_name(self) -> str | None:
        """Return the last market provider name used by the runner."""

        return self._last_market_provider_name

    @property
    def last_news_provider_name(self) -> str | None:
        """Return the last news provider name used by the runner."""

        return self._last_news_provider_name

    def run(self) -> RunnerOutput:
        """Run the complete offline SharipovAI pipeline.

        Returns:
            Runner output.
        """

        market_provider, news_provider = self._providers_for_mode(
            config_settings.settings.run_mode
        )
        self._last_market_provider_name = market_provider.name()
        self._last_news_provider_name = news_provider.name()
        market_batch = market_provider.fetch()
        tickers = self._tickers_from_market_batch(market_batch)
        orchestrator = Orchestrator()
        orchestrator.register_agent(MarketAgent())
        orchestrator.register_agent(NewsAgent(news_provider))
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
        open_positions = len(self._paper_engine.positions())
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
            reason=ai_output.decision.reason,
            consensus=ai_output.consensus.level.value,
            consensus_agreement=ai_output.consensus.agreement,
            paper_pnl=paper_account.realized_pnl + paper_account.unrealized_pnl,
            open_positions=open_positions,
        )

    def _providers_for_mode(
        self,
        run_mode: str,
    ) -> tuple[BaseDataProvider, BaseDataProvider]:
        """Create data providers for the configured run mode.

        Args:
            run_mode: Configured runner mode.

        Returns:
            Market and news providers.

        Raises:
            RunnerError: If the run mode is unsupported.
        """

        if run_mode == "demo":
            return self._create_demo_market_provider(), self._create_demo_news_provider()

        if run_mode == "live":
            return self._create_live_market_provider(), self._create_live_news_provider()

        raise RunnerError(f"Unsupported run mode: {run_mode}.")

    def _create_demo_market_provider(self) -> MarketDataProvider:
        """Create the static demo market provider."""

        return MarketDataProvider(
            items=[self._ticker_to_data_item(ticker) for ticker in self._sample_tickers()]
        )

    def _create_demo_news_provider(self) -> RSSProvider:
        """Create the static demo news provider."""

        return RSSProvider(items=self._sample_news_items())

    def _create_live_market_provider(self) -> LiveMarketProvider:
        """Create the live market provider."""

        from bybit import BybitClient

        return LiveMarketProvider(client=BybitClient())

    def _create_live_news_provider(self) -> LiveRSSProvider:
        """Create the live RSS news provider."""

        return LiveRSSProvider(feed_urls=config_settings.settings.news.rss_feeds)

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

    def _ticker_to_data_item(self, ticker: TickerInfo) -> DataItem:
        """Convert a ticker into a market data item."""

        return DataItem(
            source="demo",
            category="market",
            title=ticker.symbol,
            content=(
                f"Last price: {ticker.last_price}. "
                f"24h change: {ticker.price_24h_change_percent}. "
                f"24h turnover: {ticker.turnover_24h}."
            ),
            url=None,
            published_at=None,
            metadata={
                "symbol": ticker.symbol,
                "last_price": ticker.last_price,
                "price_24h_change_percent": ticker.price_24h_change_percent,
                "turnover_24h": ticker.turnover_24h,
                "volume_24h": ticker.volume_24h,
                "bid_price": ticker.bid_price,
                "ask_price": ticker.ask_price,
            },
        )

    def _tickers_from_market_batch(self, batch: DataBatch) -> list[TickerInfo]:
        """Convert market data items into ticker models."""

        tickers: list[TickerInfo] = []
        for item in batch.items:
            symbol = item.metadata.get("symbol", item.title)
            if not symbol:
                continue

            tickers.append(
                TickerInfo(
                    category=config_settings.settings.market.category,
                    symbol=str(symbol),
                    last_price=_optional_string(item.metadata.get("last_price")),
                    bid_price=_optional_string(item.metadata.get("bid_price")),
                    ask_price=_optional_string(item.metadata.get("ask_price")),
                    price_24h_change_percent=_optional_string(
                        item.metadata.get("price_24h_change_percent")
                    ),
                    volume_24h=_optional_string(item.metadata.get("volume_24h")),
                    turnover_24h=_optional_string(item.metadata.get("turnover_24h")),
                )
            )
        return tickers

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
            f"Mode: {config_settings.settings.run_mode}. "
            f"Market provider: {self._last_market_provider_name}. "
            f"News provider: {self._last_news_provider_name}. "
            f"Decision: {ai_output.decision.decision.value}. "
            f"Confidence: {ai_output.decision.confidence:.2f}. "
            f"Risk: {ai_output.risk.risk_level.value}. "
            f"Paper equity: {paper_account.equity:.2f}. "
            f"Learning trades: {learning_summary.total_trades}."
        )


def _optional_string(value: object) -> str | None:
    """Convert a value to an optional string."""

    if value is None:
        return None
    return str(value)
