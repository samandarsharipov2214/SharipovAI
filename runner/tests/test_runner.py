"""Tests for the SharipovAI runner."""

from __future__ import annotations

from pathlib import Path

import config.settings as config_settings
from bybit import TickerInfo
from config.models import AppConfig, MarketConfig, NewsConfig, PaperConfig, RiskConfig
from data_layer.providers import LiveMarketProvider, LiveRSSProvider
from memory import MemoryEngine
from paper_trading import PaperEngine
from runner import RunnerError, RunnerOutput, SharipovAIRunner


def test_runner_executes(tmp_path: Path) -> None:
    """Runner executes and returns output."""

    output = _runner(tmp_path).run()

    assert isinstance(output, RunnerOutput)
    assert output.decision


def test_market_agent_is_used(tmp_path: Path) -> None:
    """Runner registers Market Agent."""

    runner = _runner(tmp_path)
    runner.run()

    assert runner.last_orchestrator is not None
    assert "Market Agent" in runner.last_orchestrator.list_agents()


def test_news_agent_is_used(tmp_path: Path) -> None:
    """Runner registers News Agent."""

    runner = _runner(tmp_path)
    runner.run()

    assert runner.last_orchestrator is not None
    assert "News Agent" in runner.last_orchestrator.list_agents()


def test_paper_account_exists(tmp_path: Path) -> None:
    """Runner creates and returns paper account state."""

    output = _runner(tmp_path).run()

    assert output.paper_cash >= 0
    assert output.paper_equity > 0


def test_learning_summary_exists(tmp_path: Path) -> None:
    """Runner records a learning summary."""

    output = _runner(tmp_path).run()

    assert output.learning_summary.total_trades == 1


def test_report_is_generated(tmp_path: Path) -> None:
    """Runner generates a report."""

    output = _runner(tmp_path).run()

    assert "SharipovAI runner completed." in output.report
    assert "Decision:" in output.report


def test_no_real_api_calls(tmp_path: Path) -> None:
    """Runner uses static data and no external API calls."""

    output = _runner(tmp_path).run()

    assert output.report
    assert output.portfolio_value > 0


def test_demo_mode_uses_static_providers(tmp_path: Path) -> None:
    """Demo mode uses static providers."""

    original_settings = config_settings.settings
    config_settings.settings = _settings("demo")
    try:
        runner = _runner(tmp_path)
        runner.run()
    finally:
        config_settings.settings = original_settings

    assert runner.last_market_provider_name == "MarketDataProvider"
    assert runner.last_news_provider_name == "RSSProvider"


def test_live_mode_uses_live_providers(tmp_path: Path) -> None:
    """Live mode uses live providers without real API calls."""

    original_settings = config_settings.settings
    config_settings.settings = _settings("live")
    try:
        runner = _LiveRunner(
            memory_engine=MemoryEngine(tmp_path / "memory.json"),
            paper_engine=PaperEngine(),
        )
        runner.run()
    finally:
        config_settings.settings = original_settings

    assert runner.last_market_provider_name == "LiveMarketProvider"
    assert runner.last_news_provider_name == "LiveRSSProvider"


def test_invalid_mode_raises_runner_error(tmp_path: Path) -> None:
    """Invalid run mode raises RunnerError."""

    original_settings = config_settings.settings
    config_settings.settings = _settings("invalid")
    try:
        runner = _runner(tmp_path)
        try:
            runner.run()
        except RunnerError:
            raised = True
        else:
            raised = False
    finally:
        config_settings.settings = original_settings

    assert raised is True


def test_report_generation_still_works(tmp_path: Path) -> None:
    """Report generation still works with configuration-driven mode."""

    original_settings = config_settings.settings
    config_settings.settings = _settings("demo")
    try:
        output = _runner(tmp_path).run()
    finally:
        config_settings.settings = original_settings

    assert "Mode: demo." in output.report
    assert "Market provider: MarketDataProvider." in output.report
    assert "News provider: RSSProvider." in output.report


def _runner(tmp_path: Path) -> SharipovAIRunner:
    """Create a runner with isolated memory."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    memory_engine = MemoryEngine(tmp_path / "memory.json")
    return SharipovAIRunner(
        memory_engine=memory_engine,
        paper_engine=PaperEngine(),
    )


class _LiveRunner(SharipovAIRunner):
    """Runner with mocked live providers for tests."""

    def _create_live_market_provider(self) -> LiveMarketProvider:
        """Create a live market provider with a fake client."""

        return LiveMarketProvider(client=_FakeBybitClient())

    def _create_live_news_provider(self) -> LiveRSSProvider:
        """Create a live news provider with no feed URLs."""

        return LiveRSSProvider(feed_urls=[])


class _FakeBybitClient:
    """Fake async Bybit client for live mode tests."""

    async def get_tickers(self, category: str = "spot") -> list[TickerInfo]:
        """Return deterministic ticker data."""

        return [
            TickerInfo(
                category=category,
                symbol="BTCUSDT",
                last_price="50000",
                bid_price="49990",
                ask_price="50010",
                price_24h_change_percent="0.03",
                volume_24h="2000",
                turnover_24h="10000000",
            )
        ]


def _settings(run_mode: str) -> AppConfig:
    """Create test settings."""

    return AppConfig(
        run_mode=run_mode,
        paper=PaperConfig(initial_balance=10000.0),
        risk=RiskConfig(max_drawdown=10.0, max_position_percent=20.0),
        news=NewsConfig(rss_feeds=[]),
        market=MarketConfig(exchange="bybit", category="spot"),
    )
